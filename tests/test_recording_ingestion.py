from __future__ import annotations

from app.calling.models import CallDirection, CallProvider, CallSession
from app.calling.recording_ingestion import RecordingIngestionService
from app.calling.recording_registry import RecordingRegistry
from app.calling.recording_resolver import RecordingResolver


def _session() -> CallSession:
    return CallSession(
        session_id="session-1",
        run_id="run-1",
        direction=CallDirection.outbound,
        provider=CallProvider.twilio,
        provider_name="twilio",
        provider_call_id="CA123",
    )


def test_recording_resolver_maps_twilio_recording_payload():
    recording = RecordingResolver().resolve(
        provider_name="twilio",
        session=_session(),
        payload={
            "CallSid": "CA123",
            "RecordingSid": "RE123",
            "RecordingUrl": "https://api.twilio.com/recordings/RE123",
            "RecordingDuration": "9",
            "Channels": "2",
        },
    )

    assert recording.provider_recording_id == "RE123"
    assert recording.remote_url == "https://api.twilio.com/recordings/RE123"
    assert recording.duration_seconds == 9.0
    assert recording.channels == 2


def test_recording_registry_upsert_is_idempotent():
    registry = RecordingRegistry()
    service = RecordingIngestionService(registry=registry)
    session = _session()
    payload = {
        "CallSid": "CA123",
        "RecordingSid": "RE123",
        "RecordingUrl": "https://api.twilio.com/recordings/RE123",
        "RecordingDuration": "9",
    }

    first = service.ingest(provider_name="twilio", session=session, payload=payload)
    second = service.ingest(provider_name="twilio", session=session, payload=payload)

    assert first.provider_recording_id == "RE123"
    assert second.provider_recording_id == "RE123"
    assert len(registry.list(session_id="session-1")) == 1
    assert registry.exists("RE123")


def test_recording_ingestion_ignores_payload_without_recording():
    recording = RecordingIngestionService().ingest(
        provider_name="twilio",
        session=_session(),
        payload={"CallSid": "CA123", "CallStatus": "completed"},
    )

    assert recording is None
