"""Read-only scenario failure presentation over the existing management selection."""
from copy import deepcopy
from datetime import datetime, timezone
import io
import json

from docx import Document
from pypdf import PdfReader

from app.management.consolidated_exporters import (
    render_consolidated_csv, render_consolidated_docx,
    render_consolidated_html, render_consolidated_pdf,
)
from app.management.consolidated_package import _with_bundled_references
from tests.test_management_consolidated_report import _engine, _fixture_reports, _metrics, _report, _pdf_links


def test_groups_all_selected_failed_runs_without_rejudging_or_mutation(tmp_path):
    reports = _fixture_reports()
    reports.append(_report("run-5", "scenario-z", "2026-10-21T15:00:00Z", score=.2, passed=False))
    before = deepcopy(reports)
    report = _engine(tmp_path, reports).build("chatbot:agent-1")
    assert [s.scenario_id for s in report.scenario_failures] == ["scenario-a", "scenario-z"]
    runs = [r for s in report.scenario_failures for r in s.evaluations]
    assert {r.evaluation_id for r in runs} == {"run-1", "run-5"}
    assert {r.evaluation_id for r in runs} <= set(report.selection.included_evaluation_ids)
    assert runs[0].overall_score == .5
    assert runs[0].summary == "8 of 8 evaluated metrics failed."
    assert runs[0].report_url == "/evaluations/run-1/report"
    assert reports == before
    # A later PASS does not erase a failed selected historical run.
    assert report.scenario_results[0].latest_valid_outcome == "pass"


def test_metrics_only_include_existing_evaluated_failures_in_canonical_order(tmp_path):
    metrics = _metrics(.8)
    metrics[0].update(passed=False, score=.9)  # Respect persisted result, not a new threshold.
    metrics[3].update(passed=False, score=.4)
    metrics[4].update(passed=False, evaluation_status="not_evaluated")
    metrics[5].update(passed=False, evaluation_status="error")
    metrics[6].update(passed=False, score=None)
    metrics.append(deepcopy(metrics[0]))
    report = _engine(tmp_path, [_report("fail", "s", "2026-10-21T11:00:00Z", passed=False, metrics=metrics)]).build("chatbot:agent-1")
    failed = report.scenario_failures[0].evaluations[0].failed_metrics
    assert [m.name for m in failed] == ["Goal Completion", "Context Retention"]
    assert all(m.status == "FAIL" for m in failed)
    assert all(not m.evidence and not m.recommendations for m in failed)


def test_persisted_evidence_summaries_recommendations_are_deduplicated_and_redacted(tmp_path):
    metrics = _metrics(.8)
    metrics[0].update(passed=False, evidence=[{"actual": "Recorded action", "api_key": "PRIVATE"}])
    analysis = {"metric_name": "Goal Completion", "failure_summary": "Persisted summary", "evidence": ["Recorded action"], "recommendation": "Existing corrective action"}
    payload = _report("fail", "s", "2026-10-21T11:00:00Z", passed=False, metrics=metrics, failure=[analysis, analysis])
    report = _engine(tmp_path, [payload]).build("chatbot:agent-1")
    metric = report.scenario_failures[0].evaluations[0].failed_metrics[0]
    assert metric.evidence == ["actual: Recorded action", "Recorded action"]
    assert metric.failure_summaries == ["Persisted summary"]
    assert metric.recommendations == ["Existing corrective action"]
    assert "PRIVATE" not in json.dumps(report.scenario_failures[0].model_dump())
    html = render_consolidated_html(report)
    assert "Supporting Evidence: actual: Recorded action" in html
    assert "Recommended Action: Existing corrective action" in html
    doc = Document(io.BytesIO(render_consolidated_docx(report)))
    assert "Supporting Evidence: Recorded action" in "\n".join(p.text for p in doc.paragraphs)
    assert "failed_metric" in render_consolidated_csv(report).decode("utf-8-sig")


def test_filters_empty_state_and_deleted_prebaseline_exclusion(tmp_path):
    reports = _fixture_reports()
    reports[0].update(passed=False, metrics=_metrics(.2))
    reports.append(_report("later-fail", "scenario-a", "2026-10-21T15:00:00Z", passed=False))
    engine = _engine(tmp_path, reports)
    filtered = engine.build("chatbot:agent-1", scenario_id="scenario-a", status="fail", date_from=datetime(2026,10,21,14,tzinfo=timezone.utc), date_to=datetime(2026,10,21,16,tzinfo=timezone.utc))
    assert filtered.selection.included_evaluation_ids == ["later-fail"]
    assert filtered.scenario_failures[0].evaluations[0].evaluation_id == "later-fail"
    reports.pop()  # Deleted reports are absent from the store loader.
    filtered = engine.build("chatbot:agent-1", status="fail")
    assert {r.evaluation_id for s in filtered.scenario_failures for r in s.evaluations} == {"run-1"}
    empty = engine.build("chatbot:agent-1", status="pass")
    assert empty.scenario_failures == []
    assert "No failed test scenarios were found for the selected report scope." in render_consolidated_html(empty)


def test_unknown_and_technical_runs_do_not_become_scenario_failures(tmp_path):
    reports = [
        _report("unknown", "s", "2026-10-21T11:00:00Z", passed=None, success=None, metrics=_metrics(.2)),
        _report("error", "s", "2026-10-21T12:00:00Z", passed=False, success=False, metrics=_metrics(.2)),
    ]
    report = _engine(tmp_path, reports).build("chatbot:agent-1")
    assert report.scenario_failures == []
    html = render_consolidated_html(report)
    assert "Technical Errors (not scenario FAIL)" in html
    assert report.executive_summary["unknown_outcomes"] == 1
    assert report.executive_summary["technical_errors"] == 1


def test_multiple_failed_runs_with_same_scenario_keep_distinct_references(tmp_path):
    reports = [_report(eid, "s", f"2026-10-21T{hour}:00:00Z", passed=False) for eid,hour in [("a",11),("b",12)]]
    report = _engine(tmp_path, reports).build("chatbot:agent-1")
    assert len(report.scenario_failures) == 1
    assert [r.evaluation_id for r in report.scenario_failures[0].evaluations] == ["b", "a"]


def test_long_failure_text_splits_and_package_uses_canonical_links(tmp_path):
    metrics = _metrics(.8)
    metrics[0].update(passed=False, reason="Long reason " * 90, evidence=[{"actual": "Detailed evidence " * 90}])
    report = _engine(tmp_path, [_report("fail", "s", "2026-10-21T11:00:00Z", passed=False, metrics=metrics)]).build("chatbot:agent-1")
    pdf = render_consolidated_pdf(report)
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Long reason" in text and "Detailed evidence" in text
    assert len(PdfReader(io.BytesIO(pdf)).pages) >= 3
    assert not _pdf_links(pdf)
    bundled = _with_bundled_references(report, {"fail": "Individual-Reports/s_fail.pdf"})
    assert bundled.scenario_failures[0].evaluations[0].report_url == "Individual-Reports/s_fail.pdf"
    links = _pdf_links(render_consolidated_pdf(bundled))
    assert links.count("Individual-Reports/s_fail.pdf") >= 3
    assert report.scenario_failures[0].evaluations[0].report_url == "/evaluations/fail/report"


def test_missing_evidence_never_falls_back_to_reason(tmp_path):
    report = _engine(tmp_path, [_report("fail", "s", "2026-10-21T11:00:00Z", passed=False, score=.3)]).build("chatbot:agent-1")
    section = render_consolidated_html(report).split("5. Test Scenario-wise Failures and Evidence")[1].split("6. Recommendations")[0]
    assert "Reason:" in section
    assert "Supporting Evidence:" not in section
    assert "Recommended Action:" not in section
