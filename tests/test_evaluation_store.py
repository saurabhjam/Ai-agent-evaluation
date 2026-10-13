from __future__ import annotations

from app.evaluation_store import get_evaluation_report, list_evaluation_reports, save_evaluation_report


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
