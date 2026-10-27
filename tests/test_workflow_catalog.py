from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.schemas import TestScenario as Scenario
from app.scenario_catalog import ScenarioCatalog
from app.scenario_metadata import persisted_metadata, snapshot_scenario
from app.workflow_models import WorkflowDefinition


def case_data(case_id="case_01", kind="positive", workflow="workflow_x"):
    data = {"scenario_id": case_id, "agent": {"channel": "chatbot"},
            "persona": {"name": "Alex", "goal": "Correctly handle the configured input condition.", "tone": "concise"},
            "context": {"condition": case_id}, "behavior": ["Follow only the configured condition."],
            "success_criteria": ["Agent correctly handles the configured condition."]}
    if kind:
        data["test_case"] = {"workflow_id": workflow, "type": kind, "version": "1"}
    return data


def write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


@pytest.fixture
def catalog_factory(tmp_path):
    scenarios, workflows = tmp_path / "scenarios", tmp_path / "workflows"
    scenarios.mkdir(); workflows.mkdir()
    def create(counts=(3, 3, 2), *, zero=False):
        keys = ["chatbot:agent-1", "calling:agent-1"]
        write_yaml(workflows / "workflow.yaml", {"workflow_id": "workflow_x", "name": "Account Access", "agent_keys": keys})
        if zero:
            write_yaml(workflows / "zero.yaml", {"workflow_id": "zero_cases", "name": "No authored cases", "agent_keys": keys})
        for kind, count in zip(("positive", "negative", "edge"), counts):
            for i in range(count):
                write_yaml(scenarios / f"{kind}_{i}.yaml", case_data(f"{kind}_{i}", kind))
        return ScenarioCatalog(scenarios, workflows)
    create.scenarios = scenarios
    create.workflows = workflows
    return create


@pytest.mark.parametrize("kind", [None, "positive", "negative", "edge"])
def test_schema_legacy_and_categories_preserve_criteria(kind):
    scenario = Scenario.model_validate(case_data(kind=kind))
    assert scenario.success_criteria == ["Agent correctly handles the configured condition."]
    assert (scenario.test_case.type if scenario.test_case else None) == kind


@pytest.mark.parametrize("metadata", [{"workflow_id":"workflow_x","type":"adverse"}, {"workflow_id":"workflow_x","type":"FAIL"}, {"type":"positive"}, {"workflow_id":"workflow_x","type":"positive","test_case_id":"other"}])
def test_invalid_metadata_rejected(metadata):
    data = case_data(); data["test_case"] = metadata
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)


@pytest.mark.parametrize("coverage", [{"positive":2}, {"negative":2}, {"edge":1}])
def test_required_minimum_cannot_be_lowered(coverage):
    with pytest.raises(ValidationError):
        WorkflowDefinition(workflow_id="workflow_x", name="Workflow", coverage=coverage)


def test_catalog_zero_legacy_missing_and_duplicate_ids(catalog_factory):
    catalog_factory(zero=True)
    write_yaml(catalog_factory.scenarios / "legacy.yaml", case_data("legacy", None))
    write_yaml(catalog_factory.scenarios / "missing.yaml", case_data("missing", workflow="missing_workflow"))
    write_yaml(catalog_factory.scenarios / "duplicate.yaml", case_data("positive_0"))
    catalog = ScenarioCatalog(catalog_factory.scenarios, catalog_factory.workflows)
    assert set(catalog.workflows) == {"workflow_x", "zero_cases"}
    assert any(e["scenario_id"] == "legacy" and e["workflow_id"] is None for e in catalog.discovery())
    assert {i["code"] for i in catalog.issues} >= {"duplicate_scenario_id", "missing_or_ambiguous_workflow"}
    assert all(not e["valid"] for e in catalog.entries if e["id"] == "positive_0")
    with pytest.raises(ValueError, match="ambiguous"):
        catalog.resolve(Scenario.model_validate(case_data("positive_0")))
    # Existing path-selected legacy files still work despite duplicate catalog IDs.
    assert catalog.resolve(Scenario.model_validate(case_data("positive_0", None))) is None


def test_duplicate_and_malformed_workflows_are_not_silently_chosen(catalog_factory):
    catalog_factory()
    write_yaml(catalog_factory.workflows / "duplicate.yaml", {"workflow_id":"workflow_x", "name":"Another definition"})
    write_yaml(catalog_factory.workflows / "invalid.yaml", {"workflow_id":"bad"})
    catalog = ScenarioCatalog(catalog_factory.scenarios, catalog_factory.workflows)
    assert not catalog.workflows
    assert {i["code"] for i in catalog.issues} >= {"duplicate_workflow_id", "invalid_workflow"}


def test_invalid_case_stays_visible_but_does_not_count(catalog_factory):
    catalog_factory()
    data = case_data("invalid"); data["test_case"]["type"] = "not-a-category"
    write_yaml(catalog_factory.scenarios / "invalid.yaml", data)
    catalog = ScenarioCatalog(catalog_factory.scenarios, catalog_factory.workflows)
    assert next(e for e in catalog.entries if e["id"] == "invalid")["valid"] is False


def test_snapshot_is_whitelisted_hashed_and_historically_stable(catalog_factory):
    catalog = catalog_factory()
    raw = case_data("positive_0")
    raw["agent"]["config"] = {"api_key":"DO-NOT-PERSIST", "credentials":{"password":"PRIVATE"}}
    raw["success_criteria"].append("authorization: Bearer HIDDEN")
    scenario = Scenario.model_validate(raw)
    metadata = snapshot_scenario(scenario, catalog)
    assert metadata.test_case_id == scenario.scenario_id
    assert len(metadata.scenario_hash) == 64
    assert not any(secret in metadata.model_dump_json() for secret in ["DO-NOT-PERSIST", "PRIVATE", "HIDDEN"])
    report = {"scenario_id":scenario.scenario_id, "scenario_metadata": metadata.model_dump()}
    before = deepcopy(report)
    scenario.test_case.type = "edge"
    catalog.workflows["workflow_x"].name = "Changed now"
    assert persisted_metadata(report).test_case_type == "positive"
    assert persisted_metadata(report).workflow_name == "Account Access"
    assert report == before
    assert persisted_metadata({"scenario_id":scenario.scenario_id}).workflow_id is None
    assert persisted_metadata({"scenario_id":"different", "scenario_metadata":metadata.model_dump()}).test_case_type is None


def test_new_missing_reference_is_structural_but_shortage_does_not_block(catalog_factory):
    catalog = catalog_factory((1,0,0))
    assert snapshot_scenario(Scenario.model_validate(case_data("positive_0")), catalog).workflow_id == "workflow_x"
    with pytest.raises(ValueError):
        snapshot_scenario(Scenario.model_validate(case_data("new", workflow="missing")), catalog)


@pytest.mark.parametrize("kind", ["positive", "negative", "edge"])
def test_calling_schema_keeps_structured_persona_facts_and_case_metadata(kind):
    from app.calling.scenario import CallingScenario
    raw=case_data(kind=kind)
    raw["agent"]["channel"]="calling"
    raw["persona"]["customer_reference"]="configured-reference"
    scenario=CallingScenario.model_validate(raw)
    assert scenario.persona.model_dump()["customer_reference"] == "configured-reference"
    assert scenario.test_case.type == kind
    assert scenario.success_criteria == raw["success_criteria"]


def test_selected_source_path_cannot_reuse_another_file_identity(catalog_factory):
    catalog=catalog_factory()
    scenario=Scenario.model_validate(case_data("positive_0"))
    assert catalog.resolve(scenario,source_path=catalog_factory.scenarios/"positive_0.yaml")
    with pytest.raises(ValueError,match="another file"):
        catalog.resolve(scenario,source_path=catalog_factory.scenarios/"other.yaml")


def test_malformed_persisted_metadata_falls_back_without_secret_fields():
    report={"scenario_id":"case_01","scenario_metadata":{"test_case_id":"case_01","api_key":"PRIVATE"}}
    metadata=persisted_metadata(report)
    assert metadata.workflow_id is None and metadata.test_case_type is None
    assert "PRIVATE" not in metadata.model_dump_json()
