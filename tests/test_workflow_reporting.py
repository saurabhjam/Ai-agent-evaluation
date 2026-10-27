from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import zipfile

from docx import Document
from pypdf import PdfReader
import pytest

from app.management.consolidated_exporters import render_consolidated_pdf, render_consolidated_html, render_consolidated_docx, render_consolidated_csv
from app.management.consolidated_package import build_consolidated_report_package
from app.management.consolidated_report import ConsolidatedReportEngine
from app.management.workflow_coverage import build_workflows
from app.management.service import _outcome, _score
from app.scenario_metadata import snapshot_scenario
from app.schemas import TestScenario as Scenario
from app.scenario_catalog import ScenarioCatalog
from tests.test_management_consolidated_report import _engine, _report, _pdf_links
from tests.test_workflow_catalog import catalog_factory, case_data, write_yaml


def run(eid, kind="positive", passed=True, success=True, hour=12, version="1"):
    report = _report(eid, f"{kind}_0", f"2026-10-21T{hour:02d}:00:00Z", passed=passed, success=success, score=.8 if passed else .2)
    report["scenario_metadata"] = {"workflow_id":"workflow_x", "workflow_name":"Account Access", "test_case_id":report["scenario_id"], "test_case_type":kind, "test_case_version":version}
    return report


@pytest.mark.parametrize("counts,complete", [((3,3,2),True),((2,3,2),False),((3,2,2),False),((3,3,1),False),((4,4,3),True),((0,0,0),False)])
def test_authored_readiness_is_distinct_from_repeated_runs(catalog_factory, counts, complete):
    catalog = catalog_factory(counts, zero=True)
    reports = [run(str(i)) for i in range(8)]
    groups = build_workflows(catalog, reports, "chatbot:agent-1", _outcome, _score)
    workflow = next(w for w in groups if w["workflow_id"] == "workflow_x")
    assert workflow["authored_total"] == sum(counts)
    assert workflow["coverage_status"] == ("COMPLETE" if complete else "INCOMPLETE")
    assert workflow["attempted"] == workflow["evaluated"] == 1
    assert workflow["outcome_counts"]["pass"] == 8
    assert next(w for w in groups if w["workflow_id"] == "zero_cases")["authored_total"] == 0


@pytest.mark.parametrize("kind,passed,success,state", [("negative",True,True,"pass"),("edge",True,True,"pass"),("negative",False,True,"fail"),("edge",False,False,"error")])
def test_category_never_determines_outcome(catalog_factory, kind, passed, success, state):
    groups = build_workflows(catalog_factory(), [run("one",kind,passed,success)], "chatbot:agent-1", _outcome, _score)
    workflow = next(w for w in groups if w["workflow_id"] == "workflow_x")
    assert workflow["outcome_counts"][state] == 1
    case = next(c for c in workflow["cases"] if c["evaluation_id"] == "one")
    assert case["outcome"] == state and case["test_case_type"] == kind


def test_attempted_evaluated_latest_error_and_legacy_are_separate(catalog_factory):
    reports = [run("new-error",success=False,passed=False,hour=14,version="2"),run("old-pass",hour=12)]
    legacy = _report("legacy","positive_1","2026-10-21T12:00:00Z")
    groups = build_workflows(catalog_factory(), reports+[legacy], "chatbot:agent-1", _outcome, _score)
    workflow = next(w for w in groups if w["workflow_id"] == "workflow_x")
    assert (workflow["attempted"],workflow["evaluated"],workflow["technical_errors"]) == (1,1,1)
    legacy_group = next(w for w in groups if w["workflow_id"] is None)
    assert legacy_group["authored_total"] == 0 and legacy_group["coverage_status"] == "UNCLASSIFIED"
    assert legacy_group["cases"][0]["test_case_type"] is None


def engine_with_catalog(tmp_path, catalog, reports):
    engine = _engine(tmp_path, reports)
    engine._service._catalog_loader = lambda: catalog
    return engine


def test_management_filters_baseline_deletion_and_pie_unchanged(tmp_path,catalog_factory):
    reports = [run("positive"),run("negative","negative",False),run("edge","edge",False,False),_report("old","old","2026-10-21T09:00:00Z")]
    before = deepcopy(reports)
    engine = engine_with_catalog(tmp_path,catalog_factory(),reports)
    full = engine.build("chatbot:agent-1")
    no_metadata = deepcopy(reports)
    for item in no_metadata: item.pop("scenario_metadata",None)
    plain = engine_with_catalog(tmp_path,catalog_factory(),no_metadata).build("chatbot:agent-1")
    assert full.outcome_distribution == plain.outcome_distribution
    assert [s.count for s in full.outcome_distribution.slices] == [1,1,1]
    filtered = engine.build("chatbot:agent-1",scenario_id="negative_0",status="fail",date_from=datetime(2026,10,21,11,tzinfo=timezone.utc),date_to=datetime(2026,10,21,13,tzinfo=timezone.utc))
    assert filtered.selection.included_evaluation_ids == ["negative"]
    assert next(w for w in filtered.workflows if w["workflow_id"] == "workflow_x")["attempted"] == 1
    assert reports == before
    reports.pop(1)
    assert not engine.build("chatbot:agent-1").scenario_failures


def test_exports_failure_metadata_and_package_links(tmp_path,catalog_factory):
    report = engine_with_catalog(tmp_path,catalog_factory(),[run("fail","negative",False)]).build("chatbot:agent-1")
    assert len(report.scenario_failures[0].evaluations[0].failed_metrics) == 10
    assert report.scenario_failures[0].evaluations[0].scenario_metadata.test_case_type == "negative"
    html=render_consolidated_html(report)
    doc=Document(io.BytesIO(render_consolidated_docx(report)))
    doc_text="\n".join(p.text for p in doc.paragraphs)
    pdf=render_consolidated_pdf(report)
    text="\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    for value in ("Account Access","negative","COMPLETE","Authored coverage: 8 / 8"):
        assert value in html and value in doc_text and value in text
    csv=render_consolidated_csv(report).decode("utf-8-sig")
    assert "workflow_coverage" in csv and "type=negative" in csv
    package=build_consolidated_report_package(report,report_loader=lambda eid:run(eid,"negative",False),individual_pdf_renderer=lambda _:b"%PDF-fixture")
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert set(_pdf_links(archive.read("Consolidated-Evaluation-Report.pdf"))) <= set(archive.namelist())
    assert not _pdf_links(pdf)


def test_metadata_persists_without_rewriting_legacy(tmp_path,monkeypatch,catalog_factory):
    from app.evaluation_store import save_evaluation_report,get_evaluation_report
    monkeypatch.setattr("app.evaluation_store.settings.db_path",str(tmp_path/"new.db"))
    legacy=_report("old","positive_0","2026-10-21T12:00:00Z")
    save_evaluation_report(legacy)
    catalog=catalog_factory()
    payload=run("new")
    payload["scenario_metadata"]=snapshot_scenario(Scenario.model_validate(case_data("positive_0")),catalog).model_dump()
    save_evaluation_report(payload)
    catalog.workflows["workflow_x"].name="Changed later"
    assert get_evaluation_report("old") == legacy
    assert get_evaluation_report("new")["scenario_metadata"]["workflow_name"] == "Account Access"


def test_calling_persistence_uses_same_snapshot_without_runtime_call(monkeypatch,catalog_factory):
    from app.calling.ui_api import CallingRunResponse,_persist_calling_response
    captured=[]
    monkeypatch.setattr("app.calling.ui_api.save_evaluation_report",lambda p:captured.append(deepcopy(p)) or p)
    scenario=Scenario.model_validate(case_data("negative_0","negative"))
    metadata=snapshot_scenario(scenario,catalog_factory())
    response=CallingRunResponse(evaluation_id="calling-fixture",success=False,status="failed",connection_id="agent-1",provider="vapi",created_at="2026-10-21T12:00:00Z")
    result=_persist_calling_response(response=response,scenario=scenario,scenario_metadata=metadata)
    assert result.scenario_metadata == metadata
    assert captured[0]["scenario_metadata"]["test_case_type"] == "negative"


def test_latest_success_does_not_retain_old_version_error(catalog_factory):
    reports=[run("new-success",hour=14,version="2"),run("old-error",passed=False,success=False,hour=12)]
    group=next(w for w in build_workflows(catalog_factory(),reports,"chatbot:agent-1",_outcome,_score) if w["workflow_id"] == "workflow_x")
    assert group["technical_errors"] == 0
    assert group["outcome_counts"]["error"] == group["outcome_counts"]["pass"] == 1


def test_not_evaluated_and_error_metrics_stay_out_of_case_failures(tmp_path,catalog_factory):
    report=run("failed","negative",False)
    report["metrics"][0]["evaluation_status"]="not_evaluated"
    report["metrics"][1]["evaluation_status"]="error"
    result=engine_with_catalog(tmp_path,catalog_factory(),[report]).build("chatbot:agent-1")
    assert len(result.scenario_failures[0].evaluations[0].failed_metrics) == 8


def test_workflow_endpoint_uses_same_selected_population(tmp_path,catalog_factory):
    from app.management.api import list_management_workflows
    engine=engine_with_catalog(tmp_path,catalog_factory(),[run("p"),run("n","negative",False)])
    data=list_management_workflows("chatbot:agent-1",workflow_id="workflow_x",test_case_type="negative",service=engine._service)
    assert len(data["workflows"]) == 1
    assert data["workflows"][0]["outcome_counts"]["fail"] == 1
    assert data["workflows"][0]["outcome_counts"]["pass"] == 0


@pytest.mark.parametrize("score", [None, True, "not-a-score", float("nan")])
def test_unevaluable_score_is_not_completed_execution_coverage(tmp_path,catalog_factory,score):
    payload=run("unscored")
    payload["overall_score"]=score
    report=engine_with_catalog(tmp_path,catalog_factory(),[payload]).build("chatbot:agent-1")
    workflow=next(w for w in report.workflows if w["workflow_id"] == "workflow_x")
    assert workflow["attempted"] == 1
    assert workflow["evaluated"] == 0
    assert workflow["outcome_counts"]["pass"] == 1  # Existing outcome semantics are untouched.
