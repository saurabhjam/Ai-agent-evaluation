"""Agent reporting must not treat the repository catalog as agent ownership."""
from copy import deepcopy
from datetime import datetime, timezone
import io
import zipfile

from docx import Document
from pypdf import PdfReader
import pytest

from app.management.consolidated_exporters import (
    render_consolidated_csv, render_consolidated_docx,
    render_consolidated_html, render_consolidated_pdf,
)
from app.management.consolidated_package import build_consolidated_report_package
from app.scenario_catalog import ScenarioCatalog
from tests.test_management_consolidated_report import _report
from tests.test_workflow_catalog import case_data, write_yaml
from tests.test_workflow_reporting import engine_with_catalog


@pytest.fixture
def scoped_catalog(tmp_path):
    scenarios, workflows = tmp_path / "cases", tmp_path / "definitions"
    for name in ["selected_one", "selected_two", "selected_three"]:
        write_yaml(scenarios / f"{name}.yaml", case_data(name, None))
    for i in range(10):
        write_yaml(scenarios / f"unrelated_{i}.yaml", case_data(f"unrelated_{i}", None))
    for name in ["selected_one", "unrelated_0"]:
        write_yaml(scenarios / f"duplicate_{name}.yaml", case_data(name, None))
    for workflow, keys in [("suite_a", ["chatbot:agent-1"]),
                           ("suite_b", ["chatbot:agent-2"]), ("unbound_suite", [])]:
        write_yaml(workflows / f"{workflow}.yaml", {
            "workflow_id": workflow, "name": workflow, "agent_keys": keys,
        })
        write_yaml(scenarios / f"{workflow}_case.yaml", case_data(f"{workflow}_case", workflow=workflow))
    return ScenarioCatalog(scenarios, workflows)


def selected_reports():
    return [_report(f"run-{i}", name, "2026-10-21T12:00:00Z",
                    passed=i == 0, success=i != 2)
            for i, name in enumerate(["selected_one", "selected_two", "selected_three"])]


def case_ids(workflows):
    return {c["test_case_id"] for w in workflows for c in w["cases"]}


def test_legacy_history_and_explicit_applicability_not_global_catalog(tmp_path, scoped_catalog):
    reports = selected_reports()
    other = _report("other-run", "other_history", "2026-10-21T12:00:00Z")
    other["agent_id"] = "agent-2"
    engine = engine_with_catalog(tmp_path, scoped_catalog, reports + [other])
    detail = engine._service.get_agent("chatbot:agent-1")
    legacy = next(w for w in detail.workflows if w["workflow_id"] is None)
    assert case_ids([legacy]) == {r["scenario_id"] for r in reports}
    assert all(not c["authored"] for c in legacy["cases"])
    assert case_ids(detail.workflows) == {r["scenario_id"] for r in reports} | {"suite_a_case"}
    unrun = next(w for w in detail.workflows if w["workflow_id"] == "suite_a")["cases"][0]
    assert unrun["authored"] and unrun["evaluation_id"] is None
    assert case_ids(engine._service.get_agent("chatbot:agent-2").workflows) == {"other_history", "suite_b_case"}
    assert {issue.get("id") for issue in detail.catalog_issues} == {"selected_one"}
    assert {issue.get("id") for issue in scoped_catalog.issues} >= {"selected_one", "unrelated_0"}


def test_summary_history_pie_filters_and_deletion_are_unchanged(tmp_path, scoped_catalog):
    reports = selected_reports()
    before = deepcopy(reports)
    engine = engine_with_catalog(tmp_path, scoped_catalog, reports)
    detail = engine._service.get_agent("chatbot:agent-1")
    plain = engine_with_catalog(tmp_path, ScenarioCatalog(tmp_path / "empty", tmp_path / "empty"), reports)
    plain_detail = plain._service.get_agent("chatbot:agent-1")
    assert detail.model_dump(exclude={"workflows", "catalog_issues"}) == plain_detail.model_dump(exclude={"workflows", "catalog_issues"})
    full = engine.build("chatbot:agent-1")
    assert full.executive_summary["total_evaluation_runs"] == 3
    assert full.executive_summary["unique_scenarios"] == 3
    assert full.outcome_distribution == plain.build("chatbot:agent-1").outcome_distribution
    assert [s.count for s in full.outcome_distribution.slices] == [1, 1, 1]
    filtered = engine.build("chatbot:agent-1", scenario_id="selected_two", status="fail")
    assert filtered.selection.included_evaluation_ids == ["run-1"]
    assert case_ids(filtered.workflows) == {"selected_two", "suite_a_case"}
    assert filtered.catalog_issues == []
    empty = engine.build("chatbot:agent-1", date_from=datetime(2026, 10, 22, tzinfo=timezone.utc))
    assert case_ids(empty.workflows) == {"suite_a_case"}
    assert reports == before
    reports.pop(0)
    assert "selected_one" not in case_ids(engine.build("chatbot:agent-1").workflows)
    assert engine.build("chatbot:agent-1").catalog_issues == []


@pytest.mark.parametrize("format", ["json", "html", "pdf", "docx", "csv", "package"])
def test_all_exports_share_agent_scope(tmp_path, scoped_catalog, format):
    report = engine_with_catalog(tmp_path, scoped_catalog, selected_reports()).build("chatbot:agent-1")
    if format == "json":
        text = report.model_dump_json()
    elif format == "html":
        text = render_consolidated_html(report)
    elif format == "csv":
        text = render_consolidated_csv(report).decode("utf-8-sig")
    elif format == "docx":
        text = "\n".join(p.text for p in Document(io.BytesIO(render_consolidated_docx(report))).paragraphs)
    else:
        content = render_consolidated_pdf(report)
        if format == "package":
            package = build_consolidated_report_package(
                report, report_loader=lambda eid: next(r for r in selected_reports() if r["evaluation_id"] == eid),
                individual_pdf_renderer=lambda _: b"%PDF-fixture",
            )
            with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
                content = archive.read("Consolidated-Evaluation-Report.pdf")
                assert not any("unrelated_" in name for name in archive.namelist())
        text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)
    for name in ["selected_one", "selected_two", "selected_three", "suite_a_case"]:
        assert name in text
    for name in ["unrelated_", "suite_b", "unbound_suite"]:
        assert name not in text


def test_applicable_duplicate_warning_survives_without_a_run(tmp_path, scoped_catalog):
    write_yaml(scoped_catalog.scenarios_dir / "duplicate_authored.yaml", case_data("suite_a_case", workflow="suite_a"))
    catalog = ScenarioCatalog(scoped_catalog.scenarios_dir, scoped_catalog.workflows_dir)
    service = engine_with_catalog(tmp_path, catalog, selected_reports())._service
    data = service.workflow_data("chatbot:agent-1", [], workflow_id="suite_a")
    assert not case_ids(data["workflows"])
    assert [issue["id"] for issue in data["catalog_issues"]] == ["suite_a_case"]


def test_unbound_workflow_history_does_not_associate_unrun_siblings(tmp_path, scoped_catalog):
    report = selected_reports()[0]
    report["scenario_metadata"] = {"test_case_id": report["scenario_id"], "workflow_id": "unbound_suite",
                                   "test_case_type": "positive"}
    data = engine_with_catalog(tmp_path, scoped_catalog, [report]).build("chatbot:agent-1")
    assert case_ids(data.workflows) == {"selected_one", "suite_a_case"}
    historical = next(w for w in data.workflows if w["workflow_id"] == "unbound_suite")
    assert historical["authored_total"] == 0 and historical["attempted"] == 1


def test_ambiguous_workflow_keeps_only_relevant_warning_provenance(tmp_path, scoped_catalog):
    for workflow in ["suite_a", "suite_b"]:
        write_yaml(scoped_catalog.workflows_dir / f"duplicate_{workflow}.yaml", {
            "workflow_id": workflow, "name": "Ambiguous definition",
        })
    catalog = ScenarioCatalog(scoped_catalog.scenarios_dir, scoped_catalog.workflows_dir)
    service = engine_with_catalog(tmp_path, catalog, selected_reports())._service
    data = service.workflow_data("chatbot:agent-1", [])
    assert data["workflows"] == []
    assert {issue["id"] for issue in data["catalog_issues"] if issue["code"] == "duplicate_workflow_id"} == {"suite_a"}
    assert {issue["file"] for issue in data["catalog_issues"] if issue["code"] == "missing_or_ambiguous_workflow"} == {"suite_a_case.yaml"}
    assert len(catalog.issues) > len(data["catalog_issues"])
    assert service.workflow_data("chatbot:agent-1", [], workflow_id="suite_b")["catalog_issues"] == []


def test_authored_warnings_require_matching_channel(tmp_path, scoped_catalog):
    raw = case_data("suite_a_case", workflow="suite_a")
    raw["agent"]["channel"] = "voice"
    write_yaml(scoped_catalog.scenarios_dir / "suite_a_case.yaml", raw)
    write_yaml(scoped_catalog.scenarios_dir / "duplicate_voice.yaml", raw)
    catalog = ScenarioCatalog(scoped_catalog.scenarios_dir, scoped_catalog.workflows_dir)
    data = engine_with_catalog(tmp_path, catalog, selected_reports())._service.workflow_data("chatbot:agent-1", [])
    assert data["catalog_issues"] == []
    assert case_ids(data["workflows"]) == set()
