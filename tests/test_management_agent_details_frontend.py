from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "frontend" / "static" / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
STYLES_CSS = (ROOT / "frontend" / "static" / "styles.css").read_text(encoding="utf-8")


def _between(start: str, end: str) -> str:
    start_index = APP_JS.index(start)
    return APP_JS[start_index:APP_JS.index(end, start_index)]


def test_agent_details_uses_stable_key_and_management_endpoints_only():
    source = _between("  async loadManagementAgentDetails", "  _renderManagementAgentShell")

    assert "agent.agent_key" in source
    assert "API.getManagementAgent" in source
    assert "App.loadManagementScenarios" in source
    assert "App.loadManagementEvaluationHistory" in source
    assert 'API.get("/management/agents/"' in APP_JS
    assert "API.listEvaluations" not in source


def test_agent_header_and_summary_render_management_values_without_thresholds():
    source = _between("  _renderManagementAgentShell", "  _agentSummaryCard")

    for field in (
        "agent.name",
        "agent.agent_type",
        "agent.adapter",
        "agent.provider",
        "agent.connection_status",
        "agent.agent_key",
        "agent.latest_evaluation_at",
        "agent.total_runs",
        "agent.unique_scenarios",
        "outcomes.passed",
        "outcomes.failed",
        "outcomes.error",
        "outcomes.unknown",
        "agent.overall_average_score",
    ):
        assert field in source
    assert "Consolidated Report" in source
    assert "App.openConsolidatedReport()" in source
    assert "Coming in Phase 5" not in source


def test_scenario_summary_uses_latest_valid_run_and_deduplicated_api_rows():
    source = _between("  _renderManagementScenarios", "  _refreshManagementScenarioFilter")

    assert "item.latest_valid_run" in source
    assert "item.total_runs" in source
    assert "item.scenario_id" in source
    assert "No evaluated scenarios yet." in source
    assert "latest_run" not in source


def test_history_filters_and_pagination_are_server_side():
    loader = _between("  async loadManagementEvaluationHistory", "  _renderManagementEvaluationHistory")
    filters = _between("  applyManagementHistoryFilters", "  clearManagementHistoryFilters")

    assert "API.listManagementEvaluations" in loader
    assert "page_size: 25" in loader
    assert "scenario_id: filters.scenario_id" in loader
    assert "status: filters.status" in loader
    assert "params.date_from" in loader
    assert "params.date_to" in loader
    assert "State.managementEvaluationPage" in loader
    assert "loadManagementEvaluationHistory(State.managementAgentDetail.agent_key, 1)" in filters


def test_history_keeps_pass_fail_error_unknown_and_null_score_distinct():
    history = _between("  _renderManagementEvaluationHistory", "  _managementOutcomeBadge")
    badges = _between("  _managementOutcomeBadge", "  _renderManagementPagination")

    assert 'item.status === "error"' in history
    assert 'item.overall_score === null' in history
    assert '"—"' in history
    assert 'status === "pass"' in badges
    assert 'status === "fail"' in badges
    assert 'status === "error"' in badges
    assert "UNKNOWN" in badges


def test_report_navigation_reuses_existing_professional_report():
    source = _between("  async openManagementEvaluationReport", "  returnFromProfessionalReport")

    assert 'State.reportReturnPage = "agent-details"' in source
    assert "App.openProfessionalReport" in source
    assert "API.getEvaluationReport" in APP_JS
    assert 'App.returnFromProfessionalReport()' in APP_JS
    assert "Consolidated Report" in APP_JS
    assert "generateConsolidated" not in APP_JS


def test_independent_loading_empty_error_and_retry_states_exist():
    assert "Loading agent details..." in APP_JS
    assert "Agent details could not be loaded" in APP_JS
    assert "Scenario summary could not be loaded" in APP_JS
    assert "Evaluation history could not be loaded" in APP_JS
    assert "No evaluations match the selected filters." in APP_JS
    assert "Retry" in APP_JS


def test_existing_surfaces_and_responsive_styles_remain_available():
    assert 'id="page-evaluations"' in INDEX_HTML
    assert 'id="page-eval-report"' in INDEX_HTML
    assert 'id="page-agent-details"' in INDEX_HTML
    assert ".management-history-filters" in STYLES_CSS
    assert ".agent-summary-grid" in STYLES_CSS
    assert "@media(max-width:1024px)" in STYLES_CSS
    assert "@media(max-width:768px)" in STYLES_CSS

