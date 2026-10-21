from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException

from app.management.api import (
    get_management_agent,
    list_management_agents,
    list_management_evaluations,
    list_management_scenarios,
    router,
)
from app.management.identity import AgentIdentityResolver
from app.management.service import ManagementAggregationService


def _connection(connection_id: str, name: str, agent_type: str = "chatbot", adapter: str = "rest"):
    return SimpleNamespace(
        id=connection_id,
        name=name,
        type=SimpleNamespace(value=agent_type),
        adapter=adapter,
    )


def _report(
    evaluation_id: str,
    connection_id: str,
    scenario_id: str,
    *,
    agent_type: str = "chatbot",
    score=0.8,
    passed=True,
    success=True,
    created_at="2026-10-20T10:00:00+00:00",
    metrics=None,
):
    return {
        "evaluation_id": evaluation_id,
        "agent_id": connection_id,
        "agent_type": agent_type,
        "adapter": "rest" if agent_type != "calling" else "vapi",
        "scenario_id": scenario_id,
        "overall_score": score,
        "passed": passed,
        "success": success,
        "created_at": created_at,
        "metrics": metrics if metrics is not None else [
            {"name": "Goal Completion", "score": score, "passed": passed, "evaluation_status": "evaluated"}
        ],
    }


def _service(reports, connections, calling_path: Path):
    resolver = AgentIdentityResolver(connection_loader=lambda: connections, calling_store_path=calling_path)
    return ManagementAggregationService(
        report_loader=lambda: reports,
        identity_resolver=resolver,
        baseline_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_agent_summary_groups_multiple_scenarios_and_repeated_runs(tmp_path):
    reports = [
        _report("e1", "a1", "s1", score=0.6, passed=False, created_at="2026-10-18T10:00:00+00:00"),
        _report("e2", "a1", "s1", score=0.8, created_at="2026-10-19T10:00:00+00:00"),
        _report("e3", "a1", "s2", score=1.0, created_at="2026-10-20T10:00:00+00:00"),
    ]
    service = _service(reports, [_connection("a1", "Agent One")], tmp_path / "missing.json")

    detail = service.get_agent("chatbot:a1")

    assert detail.total_runs == 3
    assert detail.unique_scenarios == 2
    assert detail.outcome_counts.passed == 2
    assert detail.outcome_counts.failed == 1
    assert detail.overall_average_score == 0.8
    assert {item.scenario_id for item in detail.scenarios} == {"s1", "s2"}
    s1 = next(item for item in detail.scenarios if item.scenario_id == "s1")
    assert s1.total_runs == 2
    assert s1.latest_valid_run.evaluation_id == "e2"
    assert s1.latest_valid_run.report_url == "/evaluations/e2/report"


def test_identical_names_and_cross_channel_id_collisions_remain_separate(tmp_path):
    calling_path = tmp_path / "calling.json"
    calling_path.write_text(json.dumps({"same": {"id": "same", "name": "Shared Name", "provider": "vapi", "credentials": {"token": "secret"}}}))
    reports = [
        _report("chat", "same", "s1"),
        _report("call", "same", "s2", agent_type="calling"),
        _report("other", "other", "s3"),
    ]
    connections = [_connection("same", "Shared Name"), _connection("other", "Shared Name")]
    service = _service(reports, connections, calling_path)

    result = service.list_agents(page_size=10)

    assert {item.agent_key for item in result.items} == {"chatbot:same", "calling:same", "chatbot:other"}
    assert sum(item.total_runs for item in result.items) == 3
    dumped = result.model_dump_json()
    assert "secret" not in dumped
    assert "credentials" not in dumped


def test_orphan_technical_error_missing_fields_and_not_evaluated_metrics(tmp_path):
    reports = [
        _report(
            "ok", "deleted", "s1", score=0.9,
            metrics=[
                {"name": "Intent", "score": 0.9, "passed": True, "evaluation_status": "evaluated"},
                {"name": "Hallucination", "score": 0.0, "passed": False, "evaluation_status": "not_evaluated"},
            ],
        ),
        _report("error", "deleted", "s1", score=0.0, passed=False, success=False),
        _report("unknown", "deleted", "s2", score=None, passed=None, success=None),
    ]
    service = _service(reports, [], tmp_path / "missing.json")

    detail = service.get_agent("chatbot:deleted")

    assert detail.connection_status == "missing"
    assert detail.outcome_counts.error == 1
    assert detail.outcome_counts.unknown == 1
    assert detail.overall_average_score == 0.9
    assert [(metric.name, metric.average_score) for metric in detail.metric_averages] == [("Intent", 0.9)]


def test_empty_agent_history_is_listed(tmp_path):
    service = _service([], [_connection("empty", "No Runs")], tmp_path / "missing.json")
    result = service.list_agents()
    assert result.total == 0


def test_pagination_filters_report_references_and_no_source_mutation(tmp_path):
    reports = [
        _report("e1", "a1", "s1", passed=True, created_at="2026-10-18T10:00:00+00:00"),
        _report("e2", "a1", "s2", passed=False, created_at="2026-10-19T10:00:00+00:00"),
        _report("e3", "a1", "s2", passed=True, created_at="2026-10-20T10:00:00+00:00"),
    ]
    original = deepcopy(reports)
    service = _service(reports, [_connection("a1", "Agent One")], tmp_path / "missing.json")

    page = service.list_evaluations("chatbot:a1", page=1, page_size=1, scenario_id="s2", status="pass")

    assert page.total == 1
    assert page.pages == 1
    assert page.items[0].evaluation_id == "e3"
    assert page.items[0].report_url == "/evaluations/e3/report"
    assert reports == original


def test_management_api_pagination_filtering_and_missing_agent(tmp_path):
    reports = [_report("e1", "a1", "s1"), _report("e2", "a2", "s2")]
    service = _service(
        reports,
        [_connection("a1", "Alpha"), _connection("a2", "Beta")],
        tmp_path / "missing.json",
    )
    app = FastAPI()
    app.include_router(router)
    paths = {route.path for route in app.routes}
    assert "/management/agents" in paths
    assert "/management/agents/{agent_key}/evaluations" in paths
    assert "/management/agents/{agent_key}/scenarios" in paths

    agents = list_management_agents(
        page=1, page_size=1, agent_type=None, provider=None, query="Alpha", service=service
    )
    assert agents.total == 1
    assert agents.items[0].agent_key == "chatbot:a1"

    evaluations = list_management_evaluations(
        "chatbot:a1", page=1, page_size=25, scenario_id="s1", status=None,
        date_from=None, date_to=None, service=service,
    )
    assert evaluations.items[0].report_url == "/evaluations/e1/report"
    assert list_management_scenarios("chatbot:a1", service=service)[0].scenario_id == "s1"

    try:
        get_management_agent("chatbot:missing", service=service)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Missing management agent should return 404")


def test_management_baseline_excludes_history_without_mutating_it(tmp_path):
    reports = [
        _report("historical", "a1", "s1", created_at="2026-10-21T10:59:59+00:00"),
        _report("current", "a1", "s2", created_at="2026-10-21T11:00:22+00:00"),
        _report("missing-date", "a1", "s3", created_at=None),
    ]
    original = deepcopy(reports)
    resolver = AgentIdentityResolver(
        connection_loader=lambda: [_connection("a1", "Agent One")],
        calling_store_path=tmp_path / "missing.json",
    )
    service = ManagementAggregationService(
        report_loader=lambda: reports,
        identity_resolver=resolver,
        baseline_at=datetime(2026, 10, 21, 11, 0, 22, tzinfo=timezone.utc),
    )

    detail = service.get_agent("chatbot:a1")

    assert detail.total_runs == 1
    assert detail.evaluations[0].evaluation_id == "current"
    assert detail.unique_scenarios == 1
    assert reports == original
