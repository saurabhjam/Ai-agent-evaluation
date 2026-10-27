"""Whitelisted execution-time snapshots; historical reads never consult YAML."""
import hashlib
import json
import re

from pydantic import ValidationError

from app.workflow_models import ScenarioMetadata


def safe_text(value):
    text = str(value or "")
    return re.sub(r"(?i)\b(api[_-]?key|token|password|secret|authorization)\b\s*[:=]\s*(?:(?:bearer|basic)\s+)?[^\s;,]+", r"\1: [REDACTED]", text)[:1200]


def snapshot_scenario(scenario, catalog=None, source_path=None):
    from app.scenario_catalog import ScenarioCatalog
    workflow = (catalog or ScenarioCatalog()).resolve(scenario, source_path=source_path) if scenario.test_case else None
    # Connection configuration is deliberately excluded, including from provenance input.
    definition = scenario.model_dump(mode="json", exclude={"agent"})
    return ScenarioMetadata(
        workflow_id=scenario.test_case.workflow_id if scenario.test_case else None,
        workflow_name=safe_text(workflow.name) if workflow else None,
        test_case_id=scenario.scenario_id,
        test_case_type=scenario.test_case.type if scenario.test_case else None,
        test_case_version=safe_text(scenario.test_case.version) or None if scenario.test_case else None,
        scenario_hash=hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        success_criteria=[safe_text(value) for value in scenario.success_criteria],
    )


def persisted_metadata(report):
    """Fail closed on malformed historical metadata, with the original case ID."""
    case_id = str(report.get("scenario_id") or "Unknown")
    raw = report.get("scenario_metadata")
    try:
        metadata = ScenarioMetadata.model_validate(raw) if raw else ScenarioMetadata(test_case_id=case_id)
        if metadata.test_case_id != case_id:
            return ScenarioMetadata(test_case_id=case_id)
        data = metadata.model_dump()
        for key in ("workflow_name", "test_case_version"):
            data[key] = safe_text(data[key]) or None
        data["success_criteria"] = [safe_text(value) for value in data["success_criteria"]]
        return ScenarioMetadata.model_validate(data)
    except (ValidationError, TypeError):
        return ScenarioMetadata(test_case_id=case_id)
