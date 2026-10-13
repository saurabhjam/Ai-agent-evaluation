from __future__ import annotations

from app.calling.models import CallDirection, CallEventType, CallStatus
from app.calling.providers.mock import MockCallProvider


def test_mock_provider_outbound_happy_path():
    provider = MockCallProvider()

    session = provider.start_outbound_call(to="+15550000002", from_="+15550000001")

    assert session.direction == CallDirection.outbound
    assert session.status == CallStatus.connected
    assert session.provider_call_id.startswith("mock-call-")
    assert provider.get_call_status(session) == CallStatus.connected

    completed = provider.end_call(session)

    assert completed.status == CallStatus.completed
    assert provider.get_call_status(completed) == CallStatus.completed
    assert [event.event_type for event in provider.fetch_events(completed)] == [
        CallEventType.call_created,
        CallEventType.call_started,
        CallEventType.call_ringing,
        CallEventType.call_connected,
        CallEventType.call_in_progress,
        CallEventType.call_completed,
    ]


def test_mock_provider_inbound_preparation_and_connect():
    provider = MockCallProvider()

    session = provider.prepare_inbound_call(expected_from="+15550000003")
    connected = provider.simulate_inbound_connected(session)

    assert session.status == CallStatus.prepared
    assert connected.status == CallStatus.connected
    assert connected.direction == CallDirection.inbound


def test_mock_provider_recording_is_placeholder_after_completion():
    provider = MockCallProvider()
    session = provider.start_outbound_call(to="+15550000002")

    assert provider.fetch_recording(session) is None

    completed = provider.end_call(session)
    recording = provider.fetch_recording(completed)
    downloaded = provider.download_recording(recording, "artifacts/call/audio")

    assert recording is not None
    assert recording.metadata["placeholder"] is True
    assert downloaded.path == "artifacts/call/audio/audio.wav"
