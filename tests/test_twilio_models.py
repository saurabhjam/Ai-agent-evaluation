from __future__ import annotations

from app.calling.models import CallEventType, CallStatus
from app.calling.twilio_events import map_twilio_event_type, map_twilio_status, twilio_payload_to_event
from app.calling.twilio_models import TwilioCallPayload, TwilioProviderSettings, TwilioRecordingPayload
from app.calling.twilio_recording import twilio_recording_to_call_recording


def test_twilio_provider_settings_are_generic_config_projection():
    settings = TwilioProviderSettings(
        account_sid="AC123",
        auth_token="token",
        phone_number="+15550000001",
        webhook_secret="secret",
        timeout_seconds=15,
    )

    assert settings.account_sid == "AC123"
    assert settings.phone_number == "+15550000001"
    assert settings.timeout_seconds == 15


def test_twilio_payload_models_serialize_aliases():
    payload = TwilioCallPayload(
        call_sid="CA123",
        account_sid="AC123",
        **{"from": "+1"},
        to="+2",
        call_status="ringing",
    )
    recording = TwilioRecordingPayload(
        recording_sid="RE123",
        call_sid="CA123",
        duration_seconds=12.0,
    )

    assert payload.from_number == "+1"
    assert payload.to_number == "+2"
    assert recording.recording_sid == "RE123"
    assert recording.duration_seconds == 12.0


def test_twilio_status_mapping_table():
    assert map_twilio_status("queued") == CallStatus.created
    assert map_twilio_status("ringing") == CallStatus.ringing
    assert map_twilio_status("in-progress") == CallStatus.in_progress
    assert map_twilio_status("completed") == CallStatus.completed
    assert map_twilio_status("busy") == CallStatus.busy
    assert map_twilio_status("failed") == CallStatus.failed
    assert map_twilio_status("no-answer") == CallStatus.no_answer
    assert map_twilio_status("canceled") == CallStatus.canceled
    assert map_twilio_status("unknown") == CallStatus.error


def test_twilio_event_mapping():
    assert map_twilio_event_type("ringing") == CallEventType.call_ringing
    assert map_twilio_event_type("completed") == CallEventType.call_completed
    assert map_twilio_event_type("no-answer") == CallEventType.call_no_answer


def test_twilio_payload_to_event_is_provider_neutral():
    event = twilio_payload_to_event(
        session_id="session-1",
        payload={
            "CallSid": "CA123",
            "AccountSid": "AC123",
            "CallStatus": "ringing",
        },
    )

    assert event.session_id == "session-1"
    assert event.event_type == CallEventType.call_ringing
    assert event.provider_name == "twilio"
    assert event.provider_metadata["call_sid"] == "CA123"
    assert event.data["status"] == "ringing"


def test_twilio_recording_mapping():
    recording = twilio_recording_to_call_recording(
        session_id="session-1",
        recording={
            "sid": "RE123",
            "call_sid": "CA123",
            "account_sid": "AC123",
            "media_url": "https://api.twilio.com/recording.wav",
            "duration": "5",
            "channels": "2",
        },
    )

    assert recording.session_id == "session-1"
    assert recording.provider_name == "twilio"
    assert recording.provider_recording_id == "RE123"
    assert recording.remote_url == "https://api.twilio.com/recording.wav"
    assert recording.duration_seconds == 5.0
    assert recording.channels == 2
