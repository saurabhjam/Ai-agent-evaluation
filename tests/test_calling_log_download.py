import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import evaluations_api
from app.calling import diagnostics
from app.calling.ui_api import CallingRunResponse
from app.config import settings
from app.log_stream import EvalLogManager


@pytest.fixture
def endpoint(monkeypatch):
    manager = EvalLogManager()
    monkeypatch.setattr(evaluations_api, "log_manager", manager)
    app = FastAPI()
    app.include_router(evaluations_api.router)
    return TestClient(app), manager


def test_known_calling_evaluation_without_trace_is_not_empty_success(endpoint, monkeypatch):
    client, manager = endpoint
    monkeypatch.setattr(evaluations_api, "get_evaluation_report", lambda eid: {"agent_type": "calling"})
    response = client.get("/evaluations/eval_calling/logs/download")
    assert response.status_code == 404
    assert "No calling diagnostic trace" in response.json()["detail"]
    assert int(response.headers["content-length"]) > 0
    assert manager.get_logs("eval_calling") == []


@pytest.mark.parametrize("report", [{"agent_type": "chatbot"}, None])
def test_other_empty_download_behavior_is_unchanged(endpoint, monkeypatch, report):
    client, _ = endpoint
    monkeypatch.setattr(evaluations_api, "get_evaluation_report", lambda eid: report)
    response = client.get("/evaluations/eval_other/logs/download")
    assert response.status_code == 200
    assert response.content == b""


def test_existing_trace_download_is_unchanged_and_does_not_query_report(endpoint, monkeypatch):
    client, manager = endpoint
    manager.add_log("eval_existing", {"timestamp": "time", "level": "DEBUG", "message": "masked trace"})

    def unexpected_query(eid):
        raise AssertionError("Downloads containing logs must not change their data path")

    monkeypatch.setattr(evaluations_api, "get_evaluation_report", unexpected_query)
    response = client.get("/evaluations/eval_existing/logs/download")
    assert response.status_code == 200
    assert response.text == "[time] DEBUG - masked trace"


def test_optional_report_lookup_failure_preserves_existing_behavior(endpoint, monkeypatch):
    client, _ = endpoint

    def unavailable(eid):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(evaluations_api, "get_evaluation_report", unavailable)
    response = client.get("/evaluations/eval_other/logs/download")
    assert response.status_code == 200
    assert response.content == b""


def test_diagnostic_evaluation_id_is_the_download_key(endpoint, monkeypatch):
    client, manager = endpoint
    monkeypatch.setattr(settings, "calling_diagnostics_enabled", True)
    monkeypatch.setattr(settings, "calling_diagnostics_encrypted_text", False)
    monkeypatch.setattr(diagnostics, "log_manager", manager)
    monkeypatch.setattr("app.evaluation_store.new_evaluation_id", lambda: "eval_correlated")

    @diagnostics.traced_evaluation
    def evaluate_without_provider():
        diagnostics.begin_turn(0)
        diagnostics.emit("test", "mocked_calling_turn", {"text": "private customer text"})
        return CallingRunResponse(success=True, status="completed", connection_id="test", provider="test", created_at="now")

    result = evaluate_without_provider()
    response = client.get(f"/evaluations/{result.evaluation_id}/logs/download")
    assert result.evaluation_id == "eval_correlated"
    assert response.status_code == 200
    assert "private customer text" not in response.text
    entries = manager.get_logs(result.evaluation_id)
    assert entries
    assert {json.loads(entry["message"])["evaluation_id"] for entry in entries} == {result.evaluation_id}


def test_disabled_capture_produces_no_records(endpoint, monkeypatch):
    client, manager = endpoint
    monkeypatch.setattr(settings, "calling_diagnostics_enabled", False)
    monkeypatch.setattr(diagnostics, "log_manager", manager)
    monkeypatch.setattr(evaluations_api, "get_evaluation_report", lambda eid: {"agent_type": "calling"})

    @diagnostics.traced_evaluation
    def evaluate_without_provider():
        diagnostics.emit("test", "mocked_calling_turn")
        return CallingRunResponse(success=True, status="completed", connection_id="test", provider="test", created_at="now")

    assert evaluate_without_provider().evaluation_id is None
    assert dict(manager.logs) == {}
    assert client.get("/evaluations/eval_disabled/logs/download").status_code == 404


def test_replacing_worker_memory_loses_trace(endpoint, monkeypatch):
    client, old_manager = endpoint
    old_manager.add_log("eval_old_worker", {"timestamp": "time", "level": "DEBUG", "message": "old trace"})
    monkeypatch.setattr(evaluations_api, "log_manager", EvalLogManager())
    monkeypatch.setattr(evaluations_api, "get_evaluation_report", lambda eid: {"agent_type": "calling"})
    assert client.get("/evaluations/eval_old_worker/logs/download").status_code == 404
