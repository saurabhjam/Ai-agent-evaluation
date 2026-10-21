from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "frontend" / "static" / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
STYLES_CSS = (ROOT / "frontend" / "static" / "styles.css").read_text(encoding="utf-8")


def _function_source(name: str, next_name: str) -> str:
    start = APP_JS.index(f"  {name}(")
    end = APP_JS.index(f"  {next_name}(", start)
    return APP_JS[start:end]


def test_dashboard_uses_management_api_only():
    source = _function_source("async loadDashboard", "async _loadAllManagementAgents")
    init_source = _function_source("async init", "async loadPersistedEvaluations")

    assert "App._loadAllManagementAgents()" in source
    assert "API.listConnections" not in source
    assert "API.listEvaluations" not in source
    assert "State.evaluations" not in source
    assert "loadPersistedEvaluations" not in init_source
    assert 'API.get("/management/agents"' in APP_JS


def test_management_summary_keeps_outcome_categories_separate():
    source = _function_source("_renderManagementSummary", "_renderManagementAgents")

    assert "outcomes.passed" in source
    assert "outcomes.failed" in source
    assert "outcomes.error" in source
    assert "stat-management-errors" in source
    assert "outcomes.unknown" not in source


def test_agent_table_renders_required_fields_and_null_score_safely():
    source = _function_source("_renderManagementAgents", "_bindManagementAgentRows")

    assert "agent.agent_key" in source
    assert "agent.total_runs" in source
    assert "agent.unique_scenarios" in source
    assert "outcomes.unknown" in source
    assert "agent.overall_average_score === null" in source
    assert "fmtScore(agent.overall_average_score)" in source
    assert "agent.comparability_warnings" in source
    assert "agent.latest_evaluation_at" in source
    assert "agent.connection_status" in source


def test_management_dashboard_has_loading_empty_and_error_states():
    assert "Loading evaluated agents..." in APP_JS
    assert "No evaluated agents yet" in APP_JS
    assert "Agents will appear here after their first evaluation." in APP_JS
    assert "Management data could not be loaded" in APP_JS
    assert "Retry" in APP_JS


def test_agent_navigation_uses_stable_agent_key_and_agent_details_route():
    assert 'data-agent-key="' in APP_JS
    assert "row.dataset.agentKey" in APP_JS
    assert 'App.navigate("agent-details"' in APP_JS
    assert "App.loadManagementAgentDetails(extra)" in APP_JS
    assert 'id="page-agent-details"' in INDEX_HTML


def test_filters_are_forwarded_to_server_supported_query_parameters():
    assert 'managementFilters: { query: "", agent_type: "", provider: "" }' in APP_JS
    assert 'id="management-search"' in INDEX_HTML
    assert 'id="management-agent-type"' in INDEX_HTML
    assert 'id="management-provider"' in INDEX_HTML
    assert "new URLSearchParams()" in APP_JS


def test_existing_evaluations_and_report_surfaces_remain_available():
    assert 'id="page-evaluations"' in INDEX_HTML
    assert 'id="page-eval-report"' in INDEX_HTML
    assert 'listEvaluations:         ()       => API.get("/evaluations")' in APP_JS
    assert 'case "evaluations":  App.loadEvaluations();' in APP_JS
    assert 'case "eval-report":  App.renderProfessionalReport(extra);' in APP_JS


def test_management_dashboard_is_responsive():
    assert ".management-filter-bar" in STYLES_CSS
    assert "@media(max-width:1024px)" in STYLES_CSS
    assert "@media(max-width:768px)" in STYLES_CSS
    assert ".management-agents-table" in STYLES_CSS

