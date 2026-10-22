from __future__ import annotations

import sqlite3
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.evaluation_store import (
    delete_evaluation_report,
    get_evaluation_report,
    list_evaluation_reports,
    save_evaluation_report,
)
from app.evaluations_api import delete_evaluation
from app.management.identity import AgentIdentityResolver
from app.management.service import ManagementAggregationService


@pytest.fixture
def workspace_artifact_root():
    root = Path.cwd() / ".test-artifacts" / uuid.uuid4().hex
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_save_list_and_get_evaluation_report(tmp_path, monkeypatch):
    db_path = tmp_path / "evals.db"
    monkeypatch.setattr("app.evaluation_store.settings.db_path", str(db_path))

    saved = save_evaluation_report(
        {
            "connection_id": "conn-1",
            "provider": "vapi",
            "scenario_id": "scenario-1",
            "session_id": "session-1",
            "provider_call_id": "call-1",
            "status": "completed",
            "overall_score": 0.82,
            "passed": True,
            "created_at": "2026-10-07T10:00:00+00:00",
            "transcript": [{"speaker": "agent", "text": "Hello"}],
            "recording_metadata": [{"remote_url": "https://example.test/call.wav"}],
            "conversation_audio": {"full": "https://example.test/call.wav"},
            "recording_status": "available",
            "report": {"overall_score": 0.82},
        }
    )

    assert saved["evaluation_id"].startswith("eval_")
    assert get_evaluation_report(saved["evaluation_id"])["provider_call_id"] == "call-1"
    listed = list_evaluation_reports(connection_id="conn-1")
    assert len(listed) == 1
    assert listed[0]["recording_status"] == "available"


def test_save_evaluation_report_preserves_existing_id(tmp_path, monkeypatch):
    db_path = tmp_path / "evals.db"
    monkeypatch.setattr("app.evaluation_store.settings.db_path", str(db_path))

    saved = save_evaluation_report(
        {
            "evaluation_id": "eval-known",
            "connection_id": "conn-1",
            "provider": "mock",
            "scenario_id": "scenario-1",
            "status": "completed",
            "created_at": "2026-10-07T10:00:00+00:00",
        }
    )

    assert saved["evaluation_id"] == "eval-known"
    assert get_evaluation_report("eval-known")["connection_id"] == "conn-1"


@pytest.mark.parametrize(
    ("evaluation_id", "status", "passed", "score"),
    [
        ("eval-pass", "completed", True, 0.9),
        ("eval-fail", "completed", False, 0.4),
        ("eval-error", "error", False, None),
    ],
)
def test_delete_evaluation_removes_complete_payload_and_preserves_other_runs(
    tmp_path, monkeypatch, workspace_artifact_root, evaluation_id, status, passed, score
):
    db_path = tmp_path / "evals.db"
    artifacts = workspace_artifact_root / evaluation_id
    artifacts.mkdir(parents=True)
    (artifacts / "evidence.txt").write_text("owned evidence")
    monkeypatch.setattr("app.evaluation_store.settings.db_path", str(db_path))
    monkeypatch.setattr("app.evaluation_store._evaluation_artifact_dir", lambda _value: artifacts)

    save_evaluation_report(
        {
            "evaluation_id": evaluation_id,
            "connection_id": "agent-1",
            "scenario_id": "scenario-kept",
            "status": status,
            "passed": passed,
            "overall_score": score,
            "created_at": "2026-10-22T10:00:00+00:00",
            "metrics": [{"name": "Intent", "score": score}],
            "transcript": [{"role": "agent", "content": "Complete payload"}],
            "rag_evaluation": {"status": "available"},
            "backend_validation": {"status": "PASS"},
        }
    )
    save_evaluation_report(
        {
            "evaluation_id": "eval-other",
            "connection_id": "agent-1",
            "scenario_id": "scenario-kept",
            "status": "completed",
            "created_at": "2026-10-22T11:00:00+00:00",
        }
    )

    result = delete_evaluation_report(evaluation_id)

    assert result["deleted"] is True
    assert result["artifact_cleanup"] == "deleted"
    assert get_evaluation_report(evaluation_id) is None
    assert not artifacts.exists()
    assert get_evaluation_report("eval-other")["connection_id"] == "agent-1"
    assert [item["evaluation_id"] for item in list_evaluation_reports()] == ["eval-other"]


def test_delete_unknown_evaluation_returns_404(tmp_path, monkeypatch):
    monkeypatch.setattr("app.evaluation_store.settings.db_path", str(tmp_path / "evals.db"))
    with pytest.raises(HTTPException) as exc_info:
        delete_evaluation("eval-missing")
    assert exc_info.value.status_code == 404


def test_delete_rejects_unsafe_evaluation_id(tmp_path, monkeypatch):
    monkeypatch.setattr("app.evaluation_store.settings.db_path", str(tmp_path / "evals.db"))
    with pytest.raises(HTTPException) as exc_info:
        delete_evaluation("../shared")
    assert exc_info.value.status_code == 422


def test_delete_transaction_failure_preserves_row_and_restores_artifacts(
    tmp_path, monkeypatch, workspace_artifact_root
):
    db_path = tmp_path / "evals.db"
    artifacts = workspace_artifact_root / "eval-rollback"
    artifacts.mkdir(parents=True)
    (artifacts / "evidence.txt").write_text("must survive")
    monkeypatch.setattr("app.evaluation_store.settings.db_path", str(db_path))
    monkeypatch.setattr("app.evaluation_store._evaluation_artifact_dir", lambda _value: artifacts)
    save_evaluation_report(
        {
            "evaluation_id": "eval-rollback",
            "connection_id": "agent-1",
            "scenario_id": "scenario-1",
            "created_at": "2026-10-22T10:00:00+00:00",
        }
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TRIGGER block_evaluation_delete
            BEFORE DELETE ON evaluation_reports
            BEGIN
                SELECT RAISE(ABORT, 'blocked for rollback test');
            END;
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="blocked for rollback test"):
        delete_evaluation_report("eval-rollback")

    assert get_evaluation_report("eval-rollback") is not None
    assert artifacts.is_dir()
    assert (artifacts / "evidence.txt").read_text() == "must survive"


def test_deleted_evaluation_naturally_disappears_from_management_aggregates(tmp_path, monkeypatch):
    db_path = tmp_path / "evals.db"
    monkeypatch.setattr("app.evaluation_store.settings.db_path", str(db_path))
    for evaluation_id, score, passed in [("eval-one", 0.2, False), ("eval-two", 0.8, True)]:
        save_evaluation_report(
            {
                "evaluation_id": evaluation_id,
                "connection_id": "agent-1",
                "agent_id": "agent-1",
                "agent_type": "chatbot",
                "adapter": "rest",
                "scenario_id": "scenario-1",
                "status": "completed",
                "success": True,
                "passed": passed,
                "overall_score": score,
                "created_at": "2026-10-22T10:00:00+00:00",
                "metrics": [{"name": "Intent", "score": score, "evaluation_status": "evaluated"}],
            }
        )
    resolver = AgentIdentityResolver(
        connection_loader=lambda: [
            SimpleNamespace(
                id="agent-1",
                name="Agent One",
                type=SimpleNamespace(value="chatbot"),
                adapter="rest",
            )
        ],
        calling_store_path=tmp_path / "missing-calling.json",
    )
    service = ManagementAggregationService(
        identity_resolver=resolver,
        baseline_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert service.get_agent("chatbot:agent-1").total_runs == 2

    delete_evaluation_report("eval-one")
    detail = service.get_agent("chatbot:agent-1")

    assert detail.total_runs == 1
    assert detail.outcome_counts.passed == 1
    assert detail.outcome_counts.failed == 0
    assert detail.overall_average_score == 0.8
    assert [item.evaluation_id for item in detail.evaluations] == ["eval-two"]
