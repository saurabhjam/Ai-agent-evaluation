from __future__ import annotations

import pytest

from app.calling.models import CallDirection, CallEventType, CallProvider, CallSession, CallStatus
from app.calling.webhook_handler import TwilioWebhookHandler, WebhookHandler


def _session(status: CallStatus = CallStatus.created) -> CallSession:
    return CallSession(
        session_id="session-1",
        run_id="run-1",
        direction=CallDirection.outbound,
        provider=CallProvider.twilio,
        provider_name="twilio",
        provider_call_id="CA123",
        status=status,
        provider_metadata={"account_sid": "AC123", "call_sid": "CA123"},
    )


def _handler() -> WebhookHandler:
    handler = WebhookHandler()
    handler.register(TwilioWebhookHandler())
    return handler


@pytest.mark.parametrize(
    ("twilio_status", "expected"),
    [
        ("initiated", CallStatus.dialing),
        ("ringing", CallStatus.ringing),
        ("in-progress", CallStatus.in_progress),
        ("completed", CallStatus.completed),
        ("failed", CallStatus.failed),
        ("busy", CallStatus.busy),
        ("no-answer", CallStatus.no_answer),
    ],
)
def test_webhook_handler_updates_session_status(twilio_status, expected):
    result = _handler().handle(
        provider_name="twilio",
        session=_session(),
        payload={"CallSid": "CA123", "AccountSid": "AC123", "CallStatus": twilio_status},
    )

    assert result.session.status == expected
    assert result.event is not None
    assert result.conversation_evidence is not None
    assert result.conversation_evidence.session_id == "session-1"
    assert result.conversation_evidence.events == [result.event]


def test_webhook_handler_ingests_recording_metadata_through_registry():
    result = _handler().handle(
        provider_name="twilio",
        session=_session(status=CallStatus.completed),
        payload={
            "CallSid": "CA123",
            "AccountSid": "AC123",
            "RecordingSid": "RE123",
            "RecordingStatus": "completed",
            "RecordingUrl": "https://api.twilio.com/recordings/RE123",
            "RecordingDuration": "12",
        },
    )

    assert result.recording is not None
    assert result.recording.provider_recording_id == "RE123"
    assert result.event.event_type == CallEventType.recording_available
    assert result.session.provider_recording_id == "RE123"
    assert result.conversation_evidence.recordings == [result.recording]


def test_webhook_handler_duplicate_delivery_is_idempotent():
    handler = _handler()
    session = _session()
    payload = {"CallSid": "CA123", "AccountSid": "AC123", "CallStatus": "ringing"}

    first = handler.handle(provider_name="twilio", session=session, payload=payload)
    duplicate = handler.handle(provider_name="twilio", session=first.session, payload=payload)

    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert duplicate.ignored is True
    assert duplicate.event is None
    assert duplicate.conversation_evidence is None


def test_webhook_handler_unknown_event_maps_to_error_or_custom_without_crashing():
    result = _handler().handle(
        provider_name="twilio",
        session=_session(),
        payload={"CallSid": "CA123", "AccountSid": "AC123", "CallStatus": "mystery"},
    )

    assert result.session.status == CallStatus.error
    assert result.event.event_type == CallEventType.custom


def test_webhook_handler_unknown_provider_fails_cleanly():
    with pytest.raises(ValueError, match="No webhook handler registered"):
        WebhookHandler().handle(
            provider_name="missing",
            session=_session(),
            payload={"CallSid": "CA123"},
        )


def test_twilio_webhook_handler_event_key_distinguishes_recordings():
    handler = TwilioWebhookHandler()

    key = handler.event_key(
        {
            "CallSid": "CA123",
            "RecordingSid": "RE123",
            "RecordingStatus": "completed",
        }
    )

    assert key == "CA123:RE123:completed"
