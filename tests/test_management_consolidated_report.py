from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from docx import Document
from fastapi import FastAPI
from pypdf import PdfReader

from app.management.consolidated_exporters import (
    render_consolidated_csv,
    render_consolidated_docx,
    render_consolidated_html,
    render_consolidated_pdf,
)
from app.management.consolidated_report import METRIC_NAMES, SECTION_TITLES, ConsolidatedReportEngine
from app.management.consolidated_package import (
    ConsolidatedPackageError,
    build_consolidated_report_package,
)
from app.management.identity import AgentIdentityResolver
from app.management.api import router
from app.management.service import ManagementAggregationService


def _connection():
    return SimpleNamespace(id="agent-1", name="Portfolio Assistant", type=SimpleNamespace(value="chatbot"), adapter="rest")


def _metrics(score=0.8, *, hallucination_state="evaluated"):
    values = []
    for name in METRIC_NAMES:
        state = hallucination_state if name == "Hallucination" else "evaluated"
        values.append({
            "name": name,
            "score": None if state != "evaluated" else score,
            "passed": None if state != "evaluated" else score >= 0.7,
            "evaluation_status": state,
            "reason": f"Persisted {name} evidence",
        })
    return values


def _report(eid, scenario, created, *, score=0.8, passed=True, success=True, metrics=None, failure=None, error=None):
    return {
        "evaluation_id": eid,
        "agent_id": "agent-1",
        "agent_type": "chatbot",
        "adapter": "rest",
        "provider": "generic-rest",
        "scenario_id": scenario,
        "created_at": created,
        "overall_score": score,
        "passed": passed,
        "success": success,
        "status": "completed" if success is True else ("error" if success is False else "unknown"),
        "metrics": _metrics(score) if metrics is None else metrics,
        "failure_analysis": failure or [],
        "error": error,
    }


def _engine(tmp_path: Path, reports):
    resolver = AgentIdentityResolver(connection_loader=lambda: [_connection()], calling_store_path=tmp_path / "missing.json")
    service = ManagementAggregationService(
        report_loader=lambda: reports,
        identity_resolver=resolver,
        baseline_at=datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc),
    )
    return ConsolidatedReportEngine(service)


def _fixture_reports():
    failure = [{
        "metric_name": "Goal Completion",
        "category": "Conversation Validation",
        "severity": "high",
        "reason": "The requested workflow was not completed.",
        "technical_details": {"authorization": "Bearer TOP-SECRET"},
    }]
    bad_metrics = _metrics(0.5, hallucination_state="not_evaluated")
    bad_metrics[1]["evaluation_status"] = "error"
    bad_metrics[1]["score"] = 0.0
    return [
        _report("old", "old-scenario", "2026-10-21T09:59:00+00:00"),
        _report("run-1", "scenario-a", "2026-10-21T11:00:00+00:00", score=0.5, passed=False, metrics=bad_metrics, failure=failure),
        _report("run-2", "scenario-a", "2026-10-21T12:00:00+00:00", score=0.9),
        _report("run-3", "scenario-b", "2026-10-21T13:00:00+00:00", score=0.0, passed=False, success=False, error="Authorization: Bearer TOP-SECRET service unavailable"),
        _report("run-4", "scenario-c", "2026-10-21T14:00:00+00:00", score=None, passed=None, success=None, metrics=[]),
    ]


def test_consolidated_report_uses_post_baseline_runs_and_preserves_outcomes(tmp_path):
    report = _engine(tmp_path, _fixture_reports()).build("chatbot:agent-1")

    assert report.section_order == SECTION_TITLES
    assert report.executive_summary["total_evaluation_runs"] == 4
    assert report.executive_summary["unique_scenarios"] == 3
    assert report.executive_summary["passed_runs"] == 1
    assert report.executive_summary["failed_runs"] == 1
    assert report.executive_summary["technical_errors"] == 1
    assert report.executive_summary["unknown_outcomes"] == 1
    assert report.executive_summary["mean_selected_run_score"] == 0.7
    assert "old" not in report.selection.included_evaluation_ids
    assert len(report.consolidated_metrics) == 10


def test_metric_coverage_excludes_not_evaluated_errors_missing_and_technical_runs(tmp_path):
    report = _engine(tmp_path, _fixture_reports()).build("chatbot:agent-1")
    hallucination = next(item for item in report.consolidated_metrics if item.name == "Hallucination")
    persona = next(item for item in report.consolidated_metrics if item.name == "Persona and Tone Adherence")

    assert hallucination.average_score == 0.9
    assert hallucination.evaluated_count == 1
    assert hallucination.not_evaluated_count == 1
    assert hallucination.coverage == "1 / 4"
    assert persona.average_score == 0.9
    assert persona.error_count == 1
    assert persona.missing_count == 2


def test_scenario_uses_latest_valid_run_and_all_references_are_traceable(tmp_path):
    report = _engine(tmp_path, _fixture_reports()).build("chatbot:agent-1")
    scenario = next(item for item in report.scenario_results if item.scenario_id == "scenario-a")

    assert scenario.total_runs == 2
    assert scenario.latest_valid_evaluation_id == "run-2"
    assert scenario.latest_valid_score == 0.9
    assert scenario.report_url == "/evaluations/run-2/report"
    assert {item.evaluation_id for item in report.individual_reports} == {"run-1", "run-2", "run-3", "run-4"}


def test_failures_recommendations_history_and_empty_selection_are_deterministic(tmp_path):
    engine = _engine(tmp_path, _fixture_reports())
    report = engine.build("chatbot:agent-1")
    empty = engine.build("chatbot:agent-1", scenario_id="does-not-exist")

    assert any(not item.technical and item.metric == "Goal Completion" for item in report.critical_failures)
    assert any(item.technical for item in report.critical_failures)
    assert any(item.trigger.startswith("1 persisted Goal Completion") for item in report.recommendations)
    assert report.historical_comparison["message"] == "Insufficient comparable evaluation history"
    assert empty.executive_summary["total_evaluation_runs"] == 0
    assert empty.executive_summary["mean_selected_run_score"] is None
    assert len(empty.consolidated_metrics) == 10


def test_all_exports_preserve_section_order_and_do_not_expose_secrets(tmp_path):
    report = _engine(tmp_path, _fixture_reports()).build("chatbot:agent-1")
    html = render_consolidated_html(report)
    csv_text = render_consolidated_csv(report).decode("utf-8-sig")
    pdf = render_consolidated_pdf(report)
    docx = render_consolidated_docx(report)

    for title in SECTION_TITLES:
        assert title in html
        assert title in csv_text
    assert [html.index(title) for title in SECTION_TITLES] == sorted(html.index(title) for title in SECTION_TITLES)
    assert "TOP-SECRET" not in html + csv_text
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 5000
    document_text = "\n".join(paragraph.text for paragraph in Document(io.BytesIO(docx)).paragraphs)
    for title in SECTION_TITLES:
        assert title in document_text
    assert "TOP-SECRET" not in document_text


def test_filters_apply_to_model_and_provenance(tmp_path):
    report = _engine(tmp_path, _fixture_reports()).build("chatbot:agent-1", scenario_id="scenario-a", status="pass")
    assert report.selection.scenario_id == "scenario-a"
    assert report.selection.status == "pass"
    assert report.selection.included_evaluation_ids == ["run-2"]
    assert report.executive_summary["total_evaluation_runs"] == 1


def test_comparable_batches_produce_mathematical_history(tmp_path):
    reports = []
    for batch, hour, score in (("batch-a", 11, 0.6), ("batch-b", 12, 0.8)):
        report = _report(f"{batch}-run", "scenario-a", f"2026-10-21T{hour}:00:00+00:00", score=score, passed=score >= 0.7)
        report.update({"evaluation_batch_id": batch, "evaluation_config_hash": "config-1", "scenario_version": "v1"})
        reports.append(report)

    history = _engine(tmp_path, reports).build("chatbot:agent-1").historical_comparison

    assert history["status"] == "comparable"
    assert history["previous_batch"] == "batch-a"
    assert history["current_batch"] == "batch-b"
    assert history["mean_score_change"] == 0.2
    assert history["pass_change"] == 1
    assert history["fail_change"] == -1


def test_management_router_exposes_all_consolidated_formats():
    app = FastAPI()
    app.include_router(router)
    paths = {route.path for route in app.routes}
    base = "/management/agents/{agent_key}/consolidated-report"
    assert {base, base + "/html", base + "/pdf", base + "/docx", base + "/csv", base + "/package"}.issubset(paths)


def test_consolidated_package_contains_filtered_evaluations_and_relative_references(tmp_path):
    report = _engine(tmp_path, _fixture_reports()).build(
        "chatbot:agent-1", scenario_id="scenario-a"
    )
    payloads = {
        evaluation_id: _report(evaluation_id, "scenario-a", "2026-10-21T12:00:00+00:00")
        for evaluation_id in report.selection.included_evaluation_ids
    }
    captured = {}

    def consolidated_renderer(package_report):
        captured["report"] = package_report
        return b"%PDF-consolidated"

    package = build_consolidated_report_package(
        report,
        report_loader=payloads.get,
        individual_pdf_renderer=lambda payload: b"%PDF-" + payload["evaluation_id"].encode(),
        consolidated_pdf_renderer=consolidated_renderer,
    )

    assert package.filename == "Portfolio-Assistant-Evaluation-Report.zip"
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        names = set(archive.namelist())
        expected = {
            "Consolidated-Evaluation-Report.pdf",
            "README.txt",
            "Individual-Reports/scenario-a_run-1.pdf",
            "Individual-Reports/scenario-a_run-2.pdf",
        }
        assert names == expected
        assert archive.testzip() is None
        assert "old" not in archive.read("README.txt").decode()

    bundled_ids = {item.evaluation_id for item in captured["report"].individual_reports}
    assert bundled_ids == set(report.selection.included_evaluation_ids)
    assert all(item.report_url.startswith("Individual-Reports/") for item in captured["report"].individual_reports)
    assert "localhost" not in " ".join(item.report_url for item in captured["report"].individual_reports)
    assert all(item.report_url.startswith("/evaluations/") for item in report.individual_reports)


def test_consolidated_package_fails_atomically_when_an_individual_pdf_fails(tmp_path):
    report = _engine(tmp_path, _fixture_reports()).build(
        "chatbot:agent-1", scenario_id="scenario-a"
    )

    def broken_renderer(payload):
        if payload["evaluation_id"] == "run-2":
            raise ValueError("render failed")
        return b"%PDF-ok"

    try:
        build_consolidated_report_package(
            report,
            report_loader=lambda evaluation_id: {"evaluation_id": evaluation_id},
            individual_pdf_renderer=broken_renderer,
            consolidated_pdf_renderer=lambda _: b"%PDF-consolidated",
        )
    except ConsolidatedPackageError as exc:
        assert "run-2" in str(exc)
    else:
        raise AssertionError("Package generation should fail when any individual PDF fails")


def test_consolidated_package_uses_real_pdf_renderers(tmp_path):
    report = _engine(tmp_path, _fixture_reports()).build(
        "chatbot:agent-1", scenario_id="scenario-a", status="pass"
    )
    payloads = {
        evaluation_id: _report(evaluation_id, "scenario-a", "2026-10-21T12:00:00+00:00")
        for evaluation_id in report.selection.included_evaluation_ids
    }

    package = build_consolidated_report_package(report, report_loader=payloads.get)

    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert archive.read("Consolidated-Evaluation-Report.pdf").startswith(b"%PDF-")
        assert archive.read("Individual-Reports/scenario-a_run-2.pdf").startswith(b"%PDF-")


def _pdf_links(pdf_bytes):
    links = []
    for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
        for annotation_ref in page.get("/Annots") or []:
            annotation = annotation_ref.get_object()
            action = annotation.get("/A")
            if action and action.get("/URI"):
                links.append(str(action["/URI"]))
    return links


def test_package_pdf_links_sections_to_files_that_exist_in_archive(tmp_path):
    report = _engine(tmp_path, _fixture_reports()).build(
        "chatbot:agent-1", scenario_id="scenario-a"
    )
    payloads = {
        evaluation_id: _report(evaluation_id, "scenario-a", "2026-10-21T12:00:00+00:00")
        for evaluation_id in report.selection.included_evaluation_ids
    }
    package = build_consolidated_report_package(report, report_loader=payloads.get)

    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        pdf = archive.read("Consolidated-Evaluation-Report.pdf")
        links = _pdf_links(pdf)
        names = set(archive.namelist())

    assert links.count("Individual-Reports/scenario-a_run-1.pdf") >= 3
    assert links.count("Individual-Reports/scenario-a_run-2.pdf") >= 2
    assert set(links) <= names
    assert all("localhost" not in link for link in links)
    assert all(":\\" not in link and not link.startswith("file:") for link in links)


def test_standalone_pdf_has_no_offline_package_links_and_na_is_preserved(tmp_path):
    report = _engine(tmp_path, _fixture_reports()).build(
        "chatbot:agent-1", scenario_id="does-not-exist"
    )
    pdf = render_consolidated_pdf(report)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)

    assert not [link for link in _pdf_links(pdf) if link.startswith("Individual-Reports/")]
    assert "N/A" in text


def test_consolidated_pdf_handles_many_runs_long_names_and_long_failure_evidence(tmp_path):
    reports = []
    for index in range(12):
        scenario = f"scenario-{index}-" + ("long-name-" * 8)
        failure = [{
            "metric_name": "Response Quality",
            "category": "Conversation Validation",
            "severity": "high",
            "reason": "Persisted evidence " + ("with detailed client-visible context. " * 35),
        }]
        reports.append(_report(
            f"run-{index}", scenario, f"2026-10-21T{10 + index:02d}:00:00+00:00",
            score=0.45, passed=False, failure=failure,
        ))
    report = _engine(tmp_path, reports).build("chatbot:agent-1")

    pdf = render_consolidated_pdf(report)
    reader = PdfReader(io.BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert pdf.startswith(b"%PDF-")
    assert len(reader.pages) >= 5
    assert all(title in text for title in SECTION_TITLES)
    assert "Persisted evidence" in text


def test_package_sanitizes_unsafe_scenario_names_without_changing_mapping(tmp_path):
    reports = [_report("eval-safe", "../../unsafe\\scenario:name", "2026-10-21T12:00:00+00:00")]
    report = _engine(tmp_path, reports).build("chatbot:agent-1")
    package = build_consolidated_report_package(
        report,
        report_loader=lambda evaluation_id: {"evaluation_id": evaluation_id},
        individual_pdf_renderer=lambda _: b"%PDF-individual",
        consolidated_pdf_renderer=lambda _: b"%PDF-consolidated",
    )

    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        individual = [name for name in archive.namelist() if name.startswith("Individual-Reports/")]

    assert individual == ["Individual-Reports/unsafe-scenario-name_eval-safe.pdf"]
    assert ".." not in individual[0]
    assert "\\" not in individual[0]
