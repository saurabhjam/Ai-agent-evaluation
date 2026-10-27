"""Offline acceptance checks for the actual authored production YAML inventory."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import io
import shutil
import subprocess
from types import SimpleNamespace
import zipfile

from docx import Document
from pypdf import PdfReader
import pytest
import yaml

from app.management.consolidated_exporters import (
    render_consolidated_csv, render_consolidated_docx,
    render_consolidated_html, render_consolidated_pdf,
)
from app.management.consolidated_package import build_consolidated_report_package
from app.management.consolidated_report import ConsolidatedReportEngine
from app.management.identity import AgentIdentityResolver, make_agent_key
from app.management.service import ManagementAggregationService, _outcome, _score
from app.management.workflow_coverage import build_workflows
from app.scenario_catalog import ROOT, ScenarioCatalog
from app.scenario_metadata import snapshot_scenario
from app.schemas import TestScenario as Scenario
from tests.test_management_consolidated_report import _report


CONNECTION_ID = "34bb6e09-fe95-4595-9b02-8633638c6948"
SOPHIA_KEY = make_agent_key("chatbot", CONNECTION_ID)
INVENTORY = {f"property_maintenance_{kind}_{i:02d}": kind
             for kind, count in [("positive", 3), ("negative", 3), ("edge", 2)]
             for i in range(1, count + 1)}
LEGACY_IDS = {"sophia_maintenance_portfolio", "sophia_portfolio_summary", "sophia_property_maintenance"}


@pytest.fixture
def catalog():
    return ScenarioCatalog()


def load_case(case_id):
    return Scenario.model_validate(yaml.safe_load((ROOT / "scenarios" / f"{case_id}.yaml").read_text(encoding="utf-8")))


def workflow(groups):
    return next(item for item in groups if item["workflow_id"] == "property_maintenance")


@pytest.fixture
def engine(tmp_path, catalog):
    reports = [_report(f"legacy-{i}", case_id, "2026-10-21T12:00:00Z", passed=i == 0, success=i != 2)
               for i, case_id in enumerate(sorted(LEGACY_IDS))]
    for report in reports:
        report["agent_id"] = CONNECTION_ID
    connection = SimpleNamespace(id=CONNECTION_ID, name="Sophia Ai", type=SimpleNamespace(value="chatbot"), adapter="rest")
    resolver = AgentIdentityResolver(connection_loader=lambda: [connection], calling_store_path=tmp_path / "absent.json")
    service = ManagementAggregationService(
        report_loader=lambda: reports, identity_resolver=resolver, catalog_loader=lambda: catalog,
        baseline_at=datetime(2026, 10, 21, 10, tzinfo=timezone.utc),
    )
    return ConsolidatedReportEngine(service), reports


def test_actual_workflow_has_explicit_sophia_applicability(catalog):
    definition = catalog.workflows["property_maintenance"]
    assert definition.name == "Property Maintenance"
    assert definition.agent_keys == [SOPHIA_KEY]
    assert definition.coverage.model_dump() == {"positive": 3, "negative": 3, "edge": 2}
    for key in ["chatbot:unrelated", make_agent_key("calling", CONNECTION_ID), make_agent_key("voice", CONNECTION_ID)]:
        assert not any(w["workflow_id"] == definition.workflow_id
                       for w in build_workflows(catalog, [], key, _outcome, _score))


def test_actual_catalog_is_unique_valid_complete_and_unrun(catalog):
    entries = [e for e in catalog.entries if (e["test_case"] or {}).get("workflow_id") == "property_maintenance"]
    assert len(entries) == 8
    assert {e["id"] for e in entries} == set(INVENTORY)
    assert all(e["valid"] and not e["issues"] and e["channel"] == "chatbot" for e in entries)
    ids = Counter(e["id"] for e in catalog.entries)
    assert all(ids[case_id] == 1 for case_id in INVENTORY)
    actual = workflow(build_workflows(catalog, [], SOPHIA_KEY, _outcome, _score))
    assert actual["authored"] == {"positive": 3, "negative": 3, "edge": 2}
    assert actual["authored_total"] == actual["required_total"] == 8
    assert actual["missing"] == {"positive": 0, "negative": 0, "edge": 0}
    assert actual["coverage_status"] == "COMPLETE"
    assert actual["attempted"] == actual["evaluated"] == actual["technical_errors"] == 0
    assert actual["outcome_counts"] == {"pass": 0, "fail": 0, "error": 0, "unknown": 0}
    assert all(c["authored"] and c["evaluation_id"] is None and c["outcome"] is None
               and c["report_url"] is None and c["test_case_version"] == "1" for c in actual["cases"])


@pytest.mark.parametrize("case_id,category", INVENTORY.items())
def test_each_actual_case_is_executable_and_fact_constrained(catalog, case_id, category):
    case = load_case(case_id)
    assert case.scenario_id == case_id
    assert case.test_case.workflow_id == "property_maintenance"
    assert case.test_case.type == category and case.test_case.version == "1"
    assert catalog.resolve(case, ROOT / "scenarios" / f"{case_id}.yaml").workflow_id == "property_maintenance"
    metadata = snapshot_scenario(case, catalog, ROOT / "scenarios" / f"{case_id}.yaml")
    assert metadata.test_case_id == case_id and metadata.workflow_id == "property_maintenance"
    assert metadata.test_case_type == category and metadata.test_case_version == "1"
    assert case.agent.channel == "chatbot" and case.agent.config == {}
    assert len(case.persona.goal) >= 50 and len(case.behavior) >= 7 and case.success_criteria
    assert case.pass_threshold == .70
    assert case.context["property_name"] == "Mason & Main - B"
    assert case.context["tenant"] == case.context["ticket_id"] == "unavailable"
    assert case.context["submission_result"] == "unknown until supported evidence is provided"
    for field in ["unit_number", "maintenance_issue", "location_in_unit", "urgency", "description"]:
        assert case.context[field]
    rules = " ".join(case.behavior)
    assert "Do not invent property, unit, maintenance issue, location, urgency, tenant, ticket ID, or submission result" in rules
    assert "unavailable" in rules and "supported" in rules
    # Category labels are metadata, never prescribed result states.
    assert not any(field in case.model_dump() for field in ["expected_outcome", "expected_fail", "expected_error"])


def test_conditions_are_distinct_and_disclosure_triggers_explicit():
    cases = {case_id: load_case(case_id) for case_id in INVENTORY}
    assert len({case.persona.goal for case in cases.values()}) == 8
    assert len({case.context["description"] for case in cases.values()}) == 8
    urgent = cases["property_maintenance_positive_01"]
    assert urgent.context["unit_number"] == "B1207" and urgent.context["urgency"] == "Urgent"
    assert "getting worse" in urgent.context["issue_progress"]
    assert cases["property_maintenance_positive_02"].context["urgency"] == "Non-urgent"
    clarification = cases["property_maintenance_positive_03"]
    assert clarification.context["initially_withheld_field"] == "unit_number"
    assert "when the agent asks" in clarification.context["disclosure_trigger"]
    assert clarification.context["unit_number"] == "B1207"
    unavailable = cases["property_maintenance_negative_01"]
    assert unavailable.context["unit_number"] == "unavailable"
    assert "Never supply B1207 or any other unit" in " ".join(unavailable.behavior)
    invalid = cases["property_maintenance_negative_02"]
    assert invalid.context["unit_number"] == "INVALID-UNIT-NOT-REGISTERED-000"
    assert "Intentionally invalid synthetic test input" in invalid.context["identifier_validity"]
    assert invalid.context["corrected_unit_number"] == "unavailable"
    vague = cases["property_maintenance_negative_03"]
    assert vague.context["initial_description"] == "Something is wrong in my unit."
    assert "only after a relevant question" in vague.context["disclosure_trigger"]
    for category in ["negative", "edge"]:
        for case_id, kind in INVENTORY.items():
            if kind == category:
                criteria = " ".join(cases[case_id].success_criteria)
                assert ("PASS" if category == "negative" else "not an expected ERROR") in criteria


def test_edge_transitions_define_values_trigger_and_single_occurrence():
    escalation = load_case("property_maintenance_edge_01")
    event = escalation.context["escalation_event"]
    assert event["initial_urgency"] == escalation.context["urgency"] == "Non-urgent"
    assert event["later_urgency"] == "Urgent"
    assert "next customer response" in event["trigger"] and "acknowledges" in event["trigger"]
    assert event["occurrence_limit"] == 1 and event["later_description"]
    correction = load_case("property_maintenance_edge_02")
    event = correction.context["location_correction"]
    assert event["initial_value"] == "Kitchen"
    assert event["corrected_value"] == event["authoritative_value"] == correction.context["location_in_unit"] == "Bathroom"
    assert "first agent maintenance follow-up" in event["trigger"] and event["occurrence_limit"] == 1
    assert escalation.persona.edge_case and correction.persona.edge_case


def test_existing_discovery_and_validation_surfaces_find_all_eight(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "_SCENARIOS_DIR", ROOT / "scenarios")
    discovered = [entry for entry in main.list_scenarios() if entry["id"] in INVENTORY]
    assert len(discovered) == 8
    for entry in discovered:
        assert entry["valid"] and entry["channel"] == "chatbot"
        assert entry["workflow_id"] == "property_maintenance"
        assert entry["test_case_type"] == INVENTORY[entry["id"]]
        assert main.validate_scenario({"yaml_text": (ROOT / entry["path"]).read_text(encoding="utf-8")})["status"] == "ok"
    assert any(w["workflow_id"] == "property_maintenance" for w in main.get_scenario_catalog()["workflows"])


@pytest.mark.parametrize("filename", ["sophia_property_maintenance.yaml", "sophia_property_maintenance1.yaml"])
def test_old_duplicate_legacy_files_still_load(catalog, filename):
    path = ROOT / "scenarios" / filename
    case = Scenario.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert case.scenario_id == "sophia_property_maintenance" and case.test_case is None
    assert case.context["unit_number"] == "B1207"
    assert catalog.resolve(case, path) is None
    assert any(issue["code"] == "duplicate_scenario_id" and issue.get("id") == case.scenario_id
               for issue in catalog.issues)


def test_management_and_consolidated_preserve_legacy_results_and_pie(engine, tmp_path):
    engine, reports = engine
    before = deepcopy(reports)
    detail = engine._service.get_agent(SOPHIA_KEY)
    assert len(detail.evaluations) == len(detail.scenarios) == 3
    assert {c["test_case_id"] for w in detail.workflows if w["workflow_id"] is None for c in w["cases"]} == LEGACY_IDS
    assert workflow(detail.workflows)["authored_total"] == 8
    result = engine.build(SOPHIA_KEY)
    original_catalog_loader = engine._service._catalog_loader
    engine._service._catalog_loader = lambda: ScenarioCatalog(tmp_path / "empty", tmp_path / "empty")
    without_authored = engine.build(SOPHIA_KEY)
    engine._service._catalog_loader = original_catalog_loader
    assert result.executive_summary == without_authored.executive_summary
    assert result.outcome_distribution == without_authored.outcome_distribution
    assert [s.count for s in result.outcome_distribution.slices] == [1, 1, 1]
    assert result.scenario_results == without_authored.scenario_results
    assert result.scenario_failures == without_authored.scenario_failures
    assert {f.scenario_id for f in result.scenario_failures}.isdisjoint(INVENTORY)
    assert result.selection.included_evaluation_ids == without_authored.selection.included_evaluation_ids
    assert all(r["scenario_id"] in LEGACY_IDS and "scenario_metadata" not in r for r in reports)
    assert reports == before


@pytest.mark.skipif(not shutil.which("node"), reason="Node required for existing frontend renderer")
def test_management_renderer_shows_eight_unrun_cases(engine):
    engine, _ = engine
    detail = engine._service.get_agent(SOPHIA_KEY)
    script = """const fs=require('fs'),vm=require('vm');const c={window:{},document:{addEventListener(){}}};vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);const d=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(c.window.App._workflowReport(d.workflows,d.catalog_issues,'all'));"""
    html = subprocess.run([shutil.which("node"), "-e", script, str(ROOT / "frontend/static/app.js")],
                          input=detail.model_dump_json(), text=True, capture_output=True, check=True, timeout=20).stdout
    assert "Property Maintenance" in html and "Authored coverage: 8 / 8" in html and "COMPLETE" in html
    assert html.count("NO SELECTED RUN") == 8
    for case_id in INVENTORY:
        assert case_id in html
    for value in ["positive", "negative", "Edge / Adverse", "3 / 3", "2 / 2", "Version", "Legacy / Unmapped"]:
        assert value in html


@pytest.mark.parametrize("format", ["html", "pdf", "docx", "csv", "package"])
def test_actual_authored_suite_exports_without_fabricating_evaluations(engine, format):
    engine, reports = engine
    report = engine.build(SOPHIA_KEY)
    if format == "html":
        text = render_consolidated_html(report)
    elif format == "csv":
        text = render_consolidated_csv(report).decode("utf-8-sig")
    elif format == "docx":
        text = "\n".join(p.text for p in Document(io.BytesIO(render_consolidated_docx(report))).paragraphs)
    else:
        content = render_consolidated_pdf(report)
        if format == "package":
            package = build_consolidated_report_package(
                report, report_loader=lambda eid: next(r for r in reports if r["evaluation_id"] == eid),
                individual_pdf_renderer=lambda _: b"%PDF-fixture",
            )
            with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
                content = archive.read("Consolidated-Evaluation-Report.pdf")
                assert not any(case_id in path for case_id in INVENTORY for path in archive.namelist())
        text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)
    assert "Property Maintenance" in text
    if format != "csv":
        assert "COMPLETE" in text and text.count("NO SELECTED RUN") == 8
    for case_id in INVENTORY:
        assert case_id in text
