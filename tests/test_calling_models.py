from __future__ import annotations

import pytest

from app.calling.artifacts import create_artifact, create_recording, expected_artifact_filename
from app.calling.events import create_call_event
from app.calling.models import (
    CallingExecutionResult,
    CallArtifactType,
    CallDirection,
    CallEventType,
    CallProvider,
    CallSession,
    CallStatus,
    CallTranscriptTurn,
    NormalizedCallTranscript,
    ProviderConfig,
    TranscriptSpeaker,
)
from app.calling.session import create_call_session, transition_call_session


def test_provider_config_serializes_vendor_neutral_fields():
    cfg = ProviderConfig(
        provider=CallProvider.twilio,
        name="primary-twilio",
        credentials_ref="secret://twilio/main",
        settings={"record": True},
    )

    data = cfg.model_dump(mode="json")

    assert data["provider"] == "twilio"
    assert data["credentials_ref"] == "secret://twilio/main"
    assert data["settings"] == {"record": True}


def test_call_session_state_transition_helpers():
    session = create_call_session(
        direction=CallDirection.outbound,
        provider=CallProvider.custom_sip,
        scenario_id="refund-call",
        from_number="+15550000001",
        to_number="+15550000002",
    )

    connected = transition_call_session(session, CallStatus.connected, timestamp="2026-10-01T10:00:00+00:00")
    completed = connected.mark_completed("2026-10-01T10:03:00+00:00")

    assert session.status == CallStatus.pending
    assert connected.status == CallStatus.connected
    assert connected.started_at == "2026-10-01T10:00:00+00:00"
    assert connected.connected_at == "2026-10-01T10:00:00+00:00"
    assert completed.status == CallStatus.completed
    assert completed.ended_at == "2026-10-01T10:03:00+00:00"


def test_failed_call_session_records_reason_without_mutating_original():
    session = CallSession(direction=CallDirection.inbound)

    failed = session.mark_failed("no inbound call received", "2026-10-01T10:05:00+00:00")

    assert session.status == CallStatus.pending
    assert failed.status == CallStatus.failed
    assert failed.metadata["failure_reason"] == "no inbound call received"
    assert failed.ended_at == "2026-10-01T10:05:00+00:00"


def test_call_event_creation_and_serialization():
    event = create_call_event(
        session_id="session-1",
        event_type=CallEventType.recording_available,
        provider_event_id="evt-123",
        data={"recording_id": "rec-123"},
    )

    data = event.model_dump(mode="json")

    assert data["session_id"] == "session-1"
    assert data["event_type"] == "recording_available"
    assert data["provider_event_id"] == "evt-123"
    assert data["data"]["recording_id"] == "rec-123"


def test_artifact_models_cover_expected_filenames():
    assert expected_artifact_filename(CallArtifactType.audio) == "audio.wav"
    assert expected_artifact_filename(CallArtifactType.agent_audio) == "agent.wav"
    assert expected_artifact_filename(CallArtifactType.customer_audio) == "customer.wav"
    assert expected_artifact_filename(CallArtifactType.transcript) == "transcript.json"
    assert expected_artifact_filename(CallArtifactType.events) == "events.json"
    assert expected_artifact_filename(CallArtifactType.metrics) == "metrics.json"
    assert expected_artifact_filename(CallArtifactType.backend) == "backend.json"
    assert expected_artifact_filename(CallArtifactType.rag) == "rag.json"
    assert expected_artifact_filename(CallArtifactType.deepeval) == "deepeval.json"
    assert expected_artifact_filename(CallArtifactType.report) == "report.html"


def test_artifact_and_recording_metadata_are_model_only():
    artifact = create_artifact(
        session_id="session-1",
        artifact_type=CallArtifactType.transcript,
        path="artifacts/calling/run-1/transcript.json",
        content_type="application/json",
    )
    recording = create_recording(
        session_id="session-1",
        remote_url="https://provider.example/recordings/rec-1",
        recording_id="rec-1",
        duration_seconds=42.5,
        channels=2,
    )

    assert artifact.artifact_type == CallArtifactType.transcript
    assert artifact.path.endswith("transcript.json")
    assert recording.artifact_type == CallArtifactType.audio
    assert recording.channels == 2
    assert recording.duration_seconds == 42.5


def test_normalized_call_transcript_serializes_turns():
    transcript = NormalizedCallTranscript(
        session_id="session-1",
        run_id="run-1",
        source="provider_transcript",
        turns=[
            CallTranscriptTurn(
                speaker=TranscriptSpeaker.customer,
                text="I need to reschedule.",
                turn_index=0,
                confidence=0.91,
            )
        ],
    )

    data = transcript.model_dump(mode="json")

    assert data["session_id"] == "session-1"
    assert data["turns"][0]["speaker"] == "customer"
    assert data["turns"][0]["confidence"] == 0.91


def test_calling_execution_result_contains_evidence_only():
    session = CallSession(direction=CallDirection.outbound)
    transcript = NormalizedCallTranscript(session_id=session.session_id, run_id=session.run_id)
    result = CallingExecutionResult(success=True, session=session, transcript=transcript)

    assert result.success is True
    assert result.session.session_id == session.session_id
    assert result.transcript is transcript
    assert result.artifacts == []
    assert result.events == []


def test_required_direction_validation():
    with pytest.raises(Exception):
        CallSession()
