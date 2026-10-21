from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "frontend" / "static" / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
STYLES = (ROOT / "frontend" / "static" / "styles.css").read_text(encoding="utf-8")


def _between(start: str, end: str) -> str:
    start_index = APP_JS.index(start)
    return APP_JS[start_index:APP_JS.index(end, start_index)]


def test_dedicated_consolidated_page_and_api_are_registered():
    assert 'id="page-consolidated-report"' in INDEX_HTML
    assert 'case "consolidated-report"' in APP_JS
    assert '"/consolidated-report"' in APP_JS
    assert "API.getConsolidatedReport" in APP_JS


def test_report_renders_backend_model_in_required_section_order():
    source = _between("  renderConsolidatedReport", "  _consolidatedToolbar")
    calls = [f"App._consolidatedSection(sections[{index}]" for index in range(8)]
    assert all(call in source for call in calls)
    assert [source.index(call) for call in calls] == sorted(source.index(call) for call in calls)
    assert "consolidated_metrics" in source
    assert "scenario_results" in source
    assert "critical_failures" in source
    assert "historical_comparison" in source
    assert "individual_reports" in source


def test_filters_and_all_download_formats_share_selection():
    source = _between("  _consolidatedToolbar", "  applyConsolidatedFilters")
    for format_name in ("pdf", "html", "docx", "csv"):
        assert f'base + "{format_name}" + suffix' in source
    assert "State.consolidatedReportFilters" in source
    assert "scenario_id" in APP_JS
    assert "date_from" in APP_JS
    assert "date_to" in APP_JS


def test_consolidated_renderer_does_not_reference_undefined_download_helper():
    toolbar_source = _between("  _consolidatedToolbar", "  applyConsolidatedFilters")
    assert "App._reportDownloadLink" in toolbar_source
    assert "  _reportDownloadLink(url, label)" in APP_JS
    download_source = _between("  _reportDownloadLink(url, label)", "  _reportDownloadButton")
    assert "href=" in download_source
    assert "download" in download_source
    button_source = _between("  _reportDownloadButton", "  _renderReportArtifacts")
    assert "App._reportDownloadLink" in button_source


def test_individual_report_links_reuse_existing_report_flow():
    source = _between("  renderConsolidatedReport", "  _consolidatedToolbar")
    assert "App.openManagementEvaluationReport" in source
    assert "consolidated-individual-report" in source
    assert "App.openProfessionalReport" in APP_JS


def test_frontend_does_not_consolidate_or_rejudge_evaluations():
    source = _between("  async loadConsolidatedReport", "  /* ══════════════════════════════════════════════════════════\n     CONNECTIONS PAGE")
    assert "API.getConsolidatedReport" in source
    assert "EvaluationService" not in source
    assert "DeepEval" not in source
    assert "calculateMetric" not in source
    assert "runScenario" not in source


def test_consolidated_layout_is_responsive():
    for selector in (".consolidated-report-shell", ".consolidated-filters", ".consolidated-stat-grid", ".consolidated-issues"):
        assert selector in STYLES
    assert "@media(max-width:1024px)" in STYLES
    assert "@media(max-width:768px)" in STYLES
