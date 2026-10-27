"""Read-only authored coverage plus distinct-case execution coverage."""
from collections import Counter

from app.scenario_metadata import persisted_metadata, safe_text


def build_workflows(catalog, reports, agent_key, outcome, score):
    groups = {}

    def group(workflow_id, name=None):
        if workflow_id not in groups:
            definition = catalog.workflows.get(workflow_id)
            required = definition.coverage.model_dump() if definition else {"positive": 3, "negative": 3, "edge": 2}
            groups[workflow_id] = {"workflow_id": workflow_id, "workflow_name": safe_text(name or (definition.name if definition else "Legacy / Unmapped")),
                                   "catalog_present": definition is not None, "required": required, "cases": [], "_cases": {}, "_reports": [], "_evaluated": set()}
        return groups[workflow_id]

    for workflow in catalog.workflows.values():
        if agent_key in workflow.agent_keys:
            group(workflow.workflow_id, workflow.name)
    for entry in catalog.entries:
        if not entry["valid"]:
            continue
        agent_type = agent_key.split(":", 1)[0]
        if agent_type in {"chatbot", "calling", "voice"} and entry["channel"] != agent_type:
            continue
        # Legacy ownership comes only from selected persisted reports below.
        metadata = entry["test_case"]
        if metadata is None:
            continue
        workflow_id = metadata.get("workflow_id")
        if workflow_id is not None and workflow_id not in groups:
            continue
        target = group(workflow_id)
        key = (entry["id"], metadata.get("type"), metadata.get("version"))
        target["_cases"][key] = {"test_case_id": entry["id"], "test_case_type": metadata.get("type"), "test_case_version": metadata.get("version"),
                                  "workflow_name": target["workflow_name"], "authored": True, "evaluation_id": None, "outcome": None,
                                  "score": None, "report_url": None, "total_runs": 0}
    for report in reports:
        metadata = persisted_metadata(report)
        target = group(metadata.workflow_id, metadata.workflow_name)
        score_value = score(report)
        if outcome(report) in {"pass", "fail"} and score_value is not None:
            target["_evaluated"].add(metadata.test_case_id)
        key = (metadata.test_case_id, metadata.test_case_type, metadata.test_case_version)
        case = target["_cases"].setdefault(key, {"test_case_id": metadata.test_case_id, "test_case_type": metadata.test_case_type,
            "test_case_version": metadata.test_case_version, "workflow_name": metadata.workflow_name or "Legacy / Unmapped", "authored": False,
            "evaluation_id": None, "outcome": None, "score": None, "report_url": None, "total_runs": 0})
        case["total_runs"] += 1
        if case["evaluation_id"] is None:
            eid = str(report.get("evaluation_id") or "")
            case.update(evaluation_id=eid, outcome=outcome(report), score=score_value, report_url=f"/evaluations/{eid}/report",
                        workflow_name=metadata.workflow_name or "Legacy / Unmapped")
        target["_reports"].append((metadata.test_case_id, outcome(report)))
    result = []
    for target in groups.values():
        cases = list(target.pop("_cases").values())
        runs = target.pop("_reports")
        evaluated = target.pop("_evaluated")
        authored = Counter(c["test_case_type"] for c in cases if c["authored"] and c["test_case_type"])
        missing = {key: max(0, value - authored[key]) for key, value in target["required"].items()}
        target.update(authored={key: authored[key] for key in target["required"]}, authored_total=sum(authored.values()),
                      required_total=sum(target["required"].values()), missing=missing,
                      coverage_status=("INCOMPLETE" if any(missing.values()) else "COMPLETE") if target["workflow_id"] else "UNCLASSIFIED",
                      attempted=len({case_id for case_id, _ in runs}), evaluated=len(evaluated),
                      technical_errors=sum(state == "error" for state in dict(reversed(runs)).values()),
                      outcome_counts={key: sum(state == key for _, state in runs) for key in ("pass", "fail", "error", "unknown")},
                      cases=sorted(cases, key=lambda c: ({"positive": 0, "negative": 1, "edge": 2}.get(c["test_case_type"], 3), c["test_case_id"], c["test_case_version"] or "")))
        result.append(target)
    return sorted(result, key=lambda w: (w["workflow_id"] is None, w["workflow_id"] or ""))


def scoped_catalog_issues(catalog, workflows, agent_key, workflow_id=None):
    """Project global validation issues onto selected or explicitly applicable cases."""
    workflow_ids = {w["workflow_id"] for w in workflows if w["workflow_id"] is not None}
    explicit_ids = {key for key, agents in catalog.workflow_agent_keys.items()
                    if agent_key in agents and (workflow_id is None or key == workflow_id)}
    workflow_ids.update(explicit_ids)
    case_ids = {case["test_case_id"] for w in workflows for case in w["cases"]}
    channel = agent_key.split(":", 1)[0]
    paths = set()
    for entry in catalog.entries:
        metadata = entry["test_case"] or {}
        applicable = metadata.get("workflow_id") in explicit_ids and entry["channel"] == channel
        if entry["id"] in case_ids or applicable:
            paths.add(entry["path"])
            case_ids.add(entry["id"])
    return [issue for issue in catalog.issues if (
        (issue["code"] == "duplicate_scenario_id" and issue.get("id") in case_ids)
        or (issue["code"] == "duplicate_workflow_id" and issue.get("id") in workflow_ids)
        or (issue["code"] in {"invalid_scenario", "missing_or_ambiguous_workflow"}
            and issue.get("file") in paths)
    )]
