from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import shutil
import subprocess

import pytest

from app.schemas import TestScenario as Scenario, MetricResult
from app.scenario_metadata import snapshot_scenario
from tests.test_workflow_catalog import catalog_factory, case_data, write_yaml
from tests.test_workflow_reporting import run, engine_with_catalog


@pytest.mark.parametrize("kind", ["positive", "negative", "edge"])
def test_real_scoring_is_category_independent_with_mocked_judge(monkeypatch, kind):
    from app.evaluation_service import EvaluationService
    from app.executor import ExecutionResult
    from app.management.consolidated_report import METRIC_NAMES
    metrics=[MetricResult(name=name,score=.85,reason="Correctly handled input",passed=True) for name in METRIC_NAMES]
    monkeypatch.setattr("app.evaluation_service.evaluate_transcript",lambda **kwargs:deepcopy(metrics))
    monkeypatch.setattr("app.evaluation_service.run_workflow_metrics",lambda _:[])
    execution=ExecutionResult(success=True,connection_id="agent-1",agent_type="chatbot",adapter="fake",started_at="2026-10-21T12:00:00Z",completed_at="2026-10-21T12:01:00Z",transcript=[{"role":"simulated_user","content":"Please validate this identifier."},{"role":"agent","content":"It is invalid; please provide a valid identifier."}])
    service=EvaluationService(backend_validation_engine=SimpleNamespace(validate=lambda *_:None),failure_analysis_engine=SimpleNamespace(generate=lambda **_:[]))
    result=service.evaluate(execution,Scenario.model_validate(case_data(kind=kind)))
    assert result.success and result.passed
    assert result.overall_score == pytest.approx(.85)
    assert [m.name for m in result.metrics] == METRIC_NAMES


def test_chatbot_boundary_stamps_snapshot_before_persistence(monkeypatch,catalog_factory):
    import app.connections.api as api
    from app.evaluation_service import EvaluationResult
    catalog=catalog_factory()
    path=catalog_factory.scenarios / "negative_0.yaml"
    connection=SimpleNamespace(id="agent-1",enabled=True)
    monkeypatch.setattr(api.repository,"get",lambda _:connection)
    monkeypatch.setattr(api,"snapshot_scenario",lambda scenario,**_:snapshot_scenario(scenario,catalog))
    monkeypatch.setattr(api,"ScenarioExecutor",lambda:SimpleNamespace(execute=lambda *_:SimpleNamespace(success=True)))
    response=EvaluationResult(success=True,agent_id="agent-1",agent_type="chatbot",adapter="fake",scenario_id="negative_0",overall_score=.9,passed=True,created_at="2026-10-21T12:00:00Z")
    monkeypatch.setattr(api,"EvaluationService",lambda:SimpleNamespace(evaluate=lambda *_:response))
    saved=[]
    monkeypatch.setattr(api,"save_evaluation_report",lambda payload:saved.append(deepcopy(payload)) or payload)
    result=api.evaluate_connection("agent-1",api.EvaluationRequest(scenario_path=str(path),evaluation_id="test-negative"))
    assert result.passed and result.scenario_metadata.test_case_type == "negative"
    assert saved[0]["scenario_metadata"]["test_case_id"] == "negative_0"


@pytest.mark.parametrize("kind", ["positive","negative","edge"])
def test_new_filters_use_only_persisted_metadata(tmp_path,catalog_factory,kind):
    reports=[run("p"),run("n","negative",False),run("e","edge",False,False)]
    engine=engine_with_catalog(tmp_path,catalog_factory(),reports)
    result=engine.build("chatbot:agent-1",workflow_id="workflow_x",test_case_type=kind)
    assert result.selection.included_evaluation_ids == [{"positive":"p","negative":"n","edge":"e"}[kind]]
    assert all(w["workflow_id"] == "workflow_x" for w in result.workflows)
    # Current YAML edits cannot change historical filter membership.
    for entry in engine._service._catalog_loader().entries:
        if entry["test_case"]: entry["test_case"]["type"]="edge"
    assert engine.build("chatbot:agent-1",test_case_type=kind).selection.included_evaluation_ids == result.selection.included_evaluation_ids


@pytest.mark.parametrize("name", ["get_consolidated_report","download_consolidated_html","download_consolidated_pdf","download_consolidated_docx","download_consolidated_csv","download_consolidated_package"])
def test_every_report_route_shares_workflow_filter_selection(tmp_path,catalog_factory,monkeypatch,name):
    import app.management.api as api
    from app.management.consolidated_package import ConsolidatedPackage
    engine=engine_with_catalog(tmp_path,catalog_factory(),[run("p"),run("n","negative",False)])
    seen=[]
    for renderer in ("render_consolidated_html","render_consolidated_pdf","render_consolidated_docx","render_consolidated_csv"):
        monkeypatch.setattr(api,renderer,lambda report:seen.append(report.selection.included_evaluation_ids) or b"fixture")
    monkeypatch.setattr(api,"build_consolidated_report_package",lambda report:seen.append(report.selection.included_evaluation_ids) or ConsolidatedPackage(content=b"fixture",filename="fixture.zip"))
    result=getattr(api,name)("chatbot:agent-1",workflow_id="workflow_x",test_case_type="negative",engine=engine)
    assert (result.selection.included_evaluation_ids if name=="get_consolidated_report" else seen[0]) == ["n"]


def test_agent_applicability_and_duplicate_authored_exclusion(catalog_factory):
    from app.management.workflow_coverage import build_workflows
    from app.management.service import _outcome, _score
    from app.scenario_catalog import ScenarioCatalog
    catalog=catalog_factory()
    catalog.workflows["workflow_x"].agent_keys=["chatbot:other"]
    assert not [w for w in build_workflows(catalog,[],"chatbot:agent-1",_outcome,_score) if w["workflow_id"]=="workflow_x"]
    write_yaml(catalog_factory.scenarios/"duplicate.yaml",case_data("positive_0"))
    catalog=ScenarioCatalog(catalog_factory.scenarios,catalog_factory.workflows)
    workflow=next(w for w in build_workflows(catalog,[],"chatbot:agent-1",_outcome,_score) if w["workflow_id"]=="workflow_x")
    assert workflow["authored"]["positive"] == 2
    assert workflow["coverage_status"] == "INCOMPLETE"


def test_authored_coverage_is_scoped_to_agent_channel(catalog_factory):
    from app.management.workflow_coverage import build_workflows
    from app.management.service import _outcome, _score
    from app.scenario_catalog import ScenarioCatalog
    catalog_factory()
    raw=case_data("positive_0")
    raw["agent"]["channel"]="calling"
    write_yaml(catalog_factory.scenarios/"positive_0.yaml",raw)
    catalog=ScenarioCatalog(catalog_factory.scenarios,catalog_factory.workflows)
    chatbot=next(w for w in build_workflows(catalog,[],"chatbot:agent-1",_outcome,_score) if w["workflow_id"]=="workflow_x")
    calling=next(w for w in build_workflows(catalog,[],"calling:agent-1",_outcome,_score) if w["workflow_id"]=="workflow_x")
    assert chatbot["authored"]["positive"] == 2
    assert calling["authored"]["positive"] == 1
    assert chatbot["coverage_status"] == calling["coverage_status"] == "INCOMPLETE"


@pytest.mark.skipif(not shutil.which("node"),reason="Node required for frontend runtime check")
@pytest.mark.parametrize("counts,status", [((3,3,2),"COMPLETE"),((2,3,2),"INCOMPLETE"),((0,0,0),"INCOMPLETE")])
def test_frontend_workflow_renderer_separates_type_outcome_and_coverage(tmp_path,catalog_factory,counts,status):
    report=engine_with_catalog(tmp_path,catalog_factory(counts),[run("negative-pass","negative")]).build("chatbot:agent-1")
    script="""const fs=require('fs'),vm=require('vm');const c={window:{},document:{addEventListener(){}}};vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);const r=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(c.window.App._workflowReport(r.workflows,r.catalog_issues,'all'));"""
    source=Path(__file__).resolve().parents[1]/"frontend/static/app.js"
    html=subprocess.run([shutil.which("node"),"-e",script,str(source)],input=report.model_dump_json(),text=True,capture_output=True,check=True,timeout=20).stdout
    for value in (status,"negative","PASS","Account Access","View Report","Type","Outcome"):
        assert value in html
    assert "<svg" in html  # Existing bounded eye icon; no new chart dependency.


def test_calling_missing_workflow_rejected_before_runtime(monkeypatch):
    import app.calling.ui_api as api
    from fastapi import HTTPException
    monkeypatch.setattr(api,"_load_store",lambda:{"agent-1":{"enabled":True,"provider":"vapi"}})
    monkeypatch.setattr(api,"_validate_connection",lambda _:SimpleNamespace(success=True))
    monkeypatch.setattr(api,"_load_scenario",lambda _:Scenario.model_validate(case_data(workflow="does_not_exist")))
    monkeypatch.setattr(api,"CallingEvaluationRuntimeRunner",lambda:pytest.fail("Runtime must not start"))
    with pytest.raises(HTTPException) as error:
        api.run_calling_evaluation("agent-1",api.CallingRunRequest(scenario_path="fixture.yaml"))
    assert error.value.status_code == 400


def test_unknown_metadata_does_not_become_error_or_fail(tmp_path,catalog_factory):
    report=run("unknown","edge",passed=None,success=None)
    result=engine_with_catalog(tmp_path,catalog_factory(),[report]).build("chatbot:agent-1")
    assert [s.count for s in result.outcome_distribution.slices] == [0,0,0]
    assert result.outcome_distribution.unknown_count == 1
    assert result.scenario_failures == []
    workflow=next(w for w in result.workflows if w["workflow_id"] == "workflow_x")
    assert workflow["evaluated"] == workflow["technical_errors"] == 0


def test_scenario_discovery_and_validation_endpoints_are_additive(tmp_path,catalog_factory,monkeypatch):
    import app.main as main
    import app.scenario_catalog as catalog_module
    from fastapi import HTTPException
    catalog=catalog_factory((1,0,0))
    monkeypatch.setattr(main,"__file__",str(tmp_path/"app"/"main.py"))
    monkeypatch.setattr(main,"_SCENARIOS_DIR",catalog_factory.scenarios)
    monkeypatch.setattr(catalog_module,"ScenarioCatalog",lambda **_:catalog)
    import yaml
    result=main.validate_scenario({"yaml_text":yaml.safe_dump(case_data("positive_0"))})
    assert result["status"] == "ok"
    discovery=main.get_scenario_catalog()
    assert discovery["scenarios"][0]["workflow_id"] == "workflow_x"
    assert main.list_scenarios()[0]["id"] == "positive_0"
    assert main.list_scenarios()[0]["channel"] == "chatbot"
    with pytest.raises(HTTPException):
        main.validate_scenario({"yaml_text":yaml.safe_dump(case_data(workflow="missing"))})


def test_legacy_result_metadata_is_not_current_catalog_classification(tmp_path,catalog_factory):
    from tests.test_management_consolidated_report import _report
    legacy=_report("legacy","negative_0","2026-10-21T12:00:00Z")
    result=engine_with_catalog(tmp_path,catalog_factory(),[legacy]).build("chatbot:agent-1")
    assert result.individual_reports[0].scenario_metadata.test_case_type is None
    assert result.individual_reports[0].scenario_metadata.workflow_id is None
    group=next(w for w in result.workflows if w["workflow_id"] is None)
    assert group["cases"][0]["outcome"] == "pass"
