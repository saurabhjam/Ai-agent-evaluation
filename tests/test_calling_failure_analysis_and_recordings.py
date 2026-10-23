from __future__ import annotations

import io
import wave

from starlette.requests import Request

from app.calling.evaluation_bridge import CallingEvaluationBridge
from app.calling.execution_result import CallingExecutionResult, CallingExecutionStatus
from app.calling.models import CallDirection, CallProvider, CallSession, CallStatus
from app.calling.recording_artifacts import persist_recordings
from app.calling.ui_api import CallingRunResponse, _persist_calling_response
from app.evaluation_service import ConversationTurn, EvaluationResult
from app.evaluation_store import get_evaluation_report, save_evaluation_report
from app.evaluations_api import download_evaluation_recording, play_evaluation_recording
from app.schemas import AgentConfig, MetricResult, Persona, TestScenario


def _scenario() -> TestScenario:
    return TestScenario(
        scenario_id="calling-analysis",
        agent=AgentConfig(channel="calling", adapter="mock"),
        persona=Persona(name="Caller", goal="Resolve the request", tone="neutral"),
    )


def _execution() -> CallingExecutionResult:
    return CallingExecutionResult(
        status=CallingExecutionStatus.completed,
        call_session=CallSession(
            direction=CallDirection.outbound,
            provider=CallProvider.vapi,
            provider_name="vapi",
            status=CallStatus.completed,
        ),
        duration_seconds=12.5,
    )


def _failed_evaluation(*, speaker: str = "agent", reason: str = "The response repeated a question.") -> EvaluationResult:
    metric = MetricResult(
        name="Conversational Quality",
        score=0.25,
        reason=reason,
        passed=False,
        threshold=0.7,
        turn_index=1,
        conversation_message_id="turn-1",
    )
    return EvaluationResult(
        success=True,
        agent_id="call",
        agent_type="calling",
        adapter="vapi",
        scenario_id="calling-analysis",
        overall_score=0.25,
        passed=False,
        conversation=[
            ConversationTurn(
                turn_index=0,
                conversation_message_id="system-0",
                message_id="system-0",
                id="system-0",
                speaker="agent",
                message="Internal prompt",
                metadata={"speaker": "system"},
            ),
            ConversationTurn(
                turn_index=1,
                conversation_message_id="turn-1",
                message_id="turn-1",
                id="turn-1",
                speaker=speaker,
                message="Captured failed turn",
                metadata={"speaker": "agent" if speaker == "agent" else "customer", "confidence": 0.91},
            ),
        ],
        metrics=[metric],
        created_at="2026-10-23T00:00:00+00:00",
    )


class _EvaluationAdapter:
    def __init__(self, result: EvaluationResult):
        self.result = result

    def evaluate(self, execution_result, scenario):
        return self.result


def test_calling_failure_analysis_is_grounded_and_excludes_system_turn():
    evaluation = CallingEvaluationBridge(adapter=_EvaluationAdapter(_failed_evaluation())).evaluate(
        _execution(), _scenario()
    )

    assert [turn.message for turn in evaluation.conversation] == ["Captured failed turn"]
    assert len(evaluation.failure_analysis) == 1
    failure = evaluation.failure_analysis[0]
    assert failure.category == "AGENT_BEHAVIOR"
    assert failure.evidence[0]["role"] == "agent"
    assert "Internal prompt" not in str(failure.conversation_snippet)


def test_calling_failure_analysis_attributes_customer_and_stt_evidence():
    persona = CallingEvaluationBridge(
        adapter=_EvaluationAdapter(_failed_evaluation(speaker="user", reason="Customer answer did not follow the request."))
    ).evaluate(_execution(), _scenario()).failure_analysis[0]
    stt = CallingEvaluationBridge(
        adapter=_EvaluationAdapter(_failed_evaluation(reason="STT transcription confidence was insufficient."))
    ).evaluate(_execution(), _scenario()).failure_analysis[0]

    assert persona.category == "PERSONA_BEHAVIOR"
    assert stt.category == "STT"
    assert stt.technical_details["likely_failure_layer"] == "STT"


def test_calling_failure_analysis_keeps_unknown_unknown():
    evaluation = _failed_evaluation(reason="Metric threshold was not met.")
    evaluation.metrics[0].turn_index = None
    evaluation.metrics[0].conversation_message_id = None
    failure = CallingEvaluationBridge(adapter=_EvaluationAdapter(evaluation)).evaluate(
        _execution(), _scenario()
    ).failure_analysis[0]

    assert failure.category == "UNKNOWN"
    assert "insufficient" in failure.root_cause


def test_calling_failure_analysis_does_not_blame_agent_for_invalid_simulator_turn():
    execution = _execution().model_copy(update={
        "execution_metadata": {
            "simulator_contract_violations": [{"turn_id": 1, "valid": False}],
        }
    })
    failure = CallingEvaluationBridge(
        adapter=_EvaluationAdapter(_failed_evaluation())
    ).evaluate(execution, _scenario()).failure_analysis[0]

    assert failure.category == "EVALUATION_INFRASTRUCTURE"
    assert "test harness" in failure.root_cause


def test_calling_persistence_promotes_failure_analysis(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "evaluations.db"))
    evaluation = CallingEvaluationBridge(adapter=_EvaluationAdapter(_failed_evaluation())).evaluate(
        _execution(), _scenario()
    )
    response = CallingRunResponse(
        success=True,
        status="completed",
        connection_id="calling-1",
        provider="vapi",
        evaluation=evaluation,
        failure_analysis=evaluation.failure_analysis or [],
        created_at="2026-10-23T00:00:00+00:00",
    )

    saved = _persist_calling_response(response=response, scenario=_scenario())
    report = get_evaluation_report(saved.evaluation_id)

    assert report["failure_analysis"] == [item.model_dump(mode="json") for item in (evaluation.failure_analysis or [])]


def _wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 8000)
    return buffer.getvalue()


class _RecordingResponse:
    def __init__(self, body: bytes, content_type: str = "audio/wav", status_code: int = 200):
        self.body = body
        self.headers = {"content-type": content_type}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        pass


def test_recording_is_materialized_and_playback_supports_ranges(monkeypatch, tmp_path):
    import app.calling.recording_artifacts as artifacts
    from app.config import settings

    monkeypatch.setattr(artifacts, "_ROOT", tmp_path / "artifacts")
    monkeypatch.setattr(artifacts.requests, "get", lambda *args, **kwargs: _RecordingResponse(_wav_bytes()))
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "evaluations.db"))
    recording = {
        "artifact_id": "recording-1",
        "artifact_type": "audio",
        "format": "wav",
        "remote_url": "https://provider.test/full-call.wav",
        "metadata": {"provider_json": {"recordingUrl": "https://provider.test/full-call.wav"}},
    }

    prepared, status, audio = persist_recordings([recording], "eval-recording")
    save_evaluation_report({
        "evaluation_id": "eval-recording",
        "created_at": "2026-10-23T00:00:00+00:00",
        "recording_metadata": prepared,
        "recording_status": status,
        "conversation_audio": audio,
    })
    request = Request({
        "type": "http",
        "method": "GET",
        "path": prepared[0]["playback_url"],
        "headers": [(b"range", b"bytes=0-31")],
    })
    playback = play_evaluation_recording("eval-recording", "recording-1", request)
    download = download_evaluation_recording("eval-recording", "recording-1", request)

    assert status == "available"
    assert prepared[0]["duration_seconds"] == 1.0
    assert prepared[0]["content_type"] == "audio/wav"
    assert "remote_url" not in prepared[0]
    assert "provider_json" not in prepared[0]["metadata"]
    assert playback.status_code == 206
    assert playback.headers["content-range"].startswith("bytes 0-31/")
    stored_path = artifacts._ROOT / prepared[0]["path"]
    assert stored_path.read_bytes()[:4] == b"RIFF"
    assert download.status_code == 200
    assert download.media_type == "audio/wav"


def test_invalid_provider_recording_is_unavailable(monkeypatch, tmp_path):
    import app.calling.recording_artifacts as artifacts

    monkeypatch.setattr(artifacts, "_ROOT", tmp_path / "artifacts")
    monkeypatch.setattr(
        artifacts.requests,
        "get",
        lambda *args, **kwargs: _RecordingResponse(b'{"expired":true}', "application/json"),
    )

    prepared, status, audio = persist_recordings(
        [{"artifact_id": "recording-1", "remote_url": "https://provider.test/expired", "format": "wav"}],
        "eval-expired",
    )

    assert status == "unavailable"
    assert prepared[0]["status"] == "unavailable"
    assert prepared[0]["path"] is None
    assert audio["full"] is None


def test_recording_materialization_uses_provider_alternate(monkeypatch, tmp_path):
    import app.calling.recording_artifacts as artifacts

    monkeypatch.setattr(artifacts, "_ROOT", tmp_path / "artifacts")
    responses = [
        _RecordingResponse(b'{"not_ready":true}', "application/json"),
        _RecordingResponse(_wav_bytes()),
    ]
    monkeypatch.setattr(artifacts.requests, "get", lambda *args, **kwargs: responses.pop(0))

    prepared, status, _ = persist_recordings(
        [{
            "artifact_id": "recording-1",
            "remote_url": "https://provider.test/combined.wav",
            "format": "wav",
            "metadata": {"alternate_remote_urls": ["https://provider.test/stereo.wav"]},
        }],
        "eval-alternate",
    )

    assert status == "available"
    assert prepared[0]["status"] == "available"
    assert "alternate_remote_urls" not in prepared[0]["metadata"]
