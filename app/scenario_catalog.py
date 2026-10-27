"""File-backed catalog. Invalid/ambiguous definitions are visible, never merged."""
from collections import defaultdict
from pathlib import Path

import yaml

from app.workflow_models import WorkflowDefinition

ROOT = Path(__file__).resolve().parents[1]


class ScenarioCatalog:
    def __init__(self, scenarios_dir=None, workflows_dir=None):
        self.scenarios_dir = Path(scenarios_dir or ROOT / "scenarios")
        self.workflows_dir = Path(workflows_dir or ROOT / "workflows")
        self.workflows = {}
        # Keep explicit applicability even for ambiguous definitions, for scoped warnings.
        self.workflow_agent_keys = {}
        self.entries = []
        self._paths = {}
        self.issues = []
        workflow_files = defaultdict(list)
        for path in sorted(self.workflows_dir.rglob("*.yaml")):
            try:
                workflow = WorkflowDefinition.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
                workflow_files[workflow.workflow_id].append((path, workflow))
            except Exception:
                self.issues.append({"code": "invalid_workflow", "file": path.name})
        for key, items in workflow_files.items():
            self.workflow_agent_keys[key] = {agent for _, workflow in items for agent in workflow.agent_keys}
            if len(items) != 1:
                self.issues.append({"code": "duplicate_workflow_id", "id": key, "files": [p.name for p, _ in items]})
            else:
                self.workflows[key] = items[0][1]
        for path in sorted(self.scenarios_dir.rglob("*.yaml")):
            entry = None
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if not isinstance(raw, dict):
                    raise ValueError("Expected mapping")
                channel = (raw.get("agent") or {}).get("channel", "chatbot")
                if "voice" in path.relative_to(self.scenarios_dir).parts:
                    channel = "voice"
                if "calling" in path.relative_to(self.scenarios_dir).parts:
                    channel = "calling"
                entry = {"id": raw.get("scenario_id", path.stem), "scenario_id": raw.get("scenario_id", path.stem),
                         "channel": channel, "path": self._path(path), "test_case": None, "valid": True, "issues": []}
                self._paths[entry["path"]] = path.resolve()
                # Legacy discovery remains permissive; opt-in cases must be executable.
                if raw.get("test_case") is not None:
                    from app.schemas import TestScenario
                    model = TestScenario
                    if channel == "calling":
                        from app.calling.scenario import CallingScenario
                        model = CallingScenario
                    scenario = model.model_validate(raw)
                    entry["test_case"] = scenario.test_case.model_dump()
                    if scenario.test_case.workflow_id not in self.workflows:
                        entry["issues"].append("missing_or_ambiguous_workflow")
                self.entries.append(entry)
            except Exception:
                if entry is not None:
                    entry["issues"].append("invalid_scenario")
                    self.entries.append(entry)
                else:
                    self.issues.append({"code": "invalid_scenario", "file": self._path(path)})
        grouped = defaultdict(list)
        for entry in self.entries:
            grouped[entry["id"]].append(entry)
        for key, entries in grouped.items():
            if len(entries) > 1:
                self.issues.append({"code": "duplicate_scenario_id", "id": key, "files": [e["path"] for e in entries]})
                for entry in entries:
                    entry["issues"].append("duplicate_scenario_id")
        for entry in self.entries:
            entry["valid"] = not entry["issues"]
            for code in entry["issues"]:
                if code != "duplicate_scenario_id":
                    self.issues.append({"code": code, "file": entry["path"]})

    def _path(self, path):
        try:
            return path.relative_to(ROOT).as_posix()
        except ValueError:
            return path.relative_to(self.scenarios_dir).as_posix()

    def resolve(self, scenario, source_path=None):
        """Legacy path selection is unchanged; opt-in identity must be unambiguous."""
        if scenario.test_case is None:
            return None
        workflow = self.workflows.get(scenario.test_case.workflow_id)
        if workflow is None:
            raise ValueError("Referenced workflow is missing or ambiguous")
        matches = [entry for entry in self.entries if entry["id"] == scenario.scenario_id]
        if len(matches) > 1:
            raise ValueError("Selected scenario ID is ambiguous")
        if matches and source_path is not None and self._paths[matches[0]["path"]] != Path(source_path).resolve():
            raise ValueError("Selected scenario ID belongs to another file")
        return workflow

    def discovery(self):
        result = []
        for entry in self.entries:
            metadata = entry["test_case"] or {}
            workflow = self.workflows.get(metadata.get("workflow_id"))
            result.append({**entry, "test_case_id": entry["id"], "workflow_id": metadata.get("workflow_id"),
                           "workflow_name": workflow.name if workflow else None, "test_case_type": metadata.get("type")})
        return result
