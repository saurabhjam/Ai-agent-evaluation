from __future__ import annotations

from types import SimpleNamespace

from app.calling.config import CallingProviderConfig
from app.calling.models import CallDirection, CallStatus
from app.calling.provider_factory import ProviderFactory
from app.calling.provider_registry import ProviderRegistry
from app.calling.providers.mock import MockCallProvider
from app.calling.providers.twilio import TwilioProvider


class FakeCalls:
    def __init__(self):
        self.created = []
        self.updated = []
        self.current = SimpleNamespace(sid="CA123", status="queued")

    def create(self, **kwargs):
        self.created.append(kwargs)
        return self.current

    def __call__(self, call_sid):
        self.call_sid = call_sid
        return self

    def fetch(self):
        return SimpleNamespace(sid=self.call_sid, status="in-progress")

    def update(self, status):
        self.updated.append(status)
        return SimpleNamespace(sid=self.call_sid, status=status)


class FakeRecordings:
    def __init__(self):
        self.queries = []

    def list(self, **kwargs):
        self.queries.append(kwargs)
        return [
            SimpleNamespace(
                sid="RE123",
                call_sid=kwargs["call_sid"],
                account_sid="AC123",
                media_url="https://api.twilio.com/recording.wav",
                duration="7",
                channels="1",
            )
        ]


class FakeTwilioClient:
    def __init__(self):
        self.calls = FakeCalls()
        self.recordings = FakeRecordings()


def _config() -> CallingProviderConfig:
    return CallingProviderConfig(
        provider_name="twilio",
        credentials={"account_sid": "AC123", "auth_token": "token"},
        settings={
            "phone_number": "+15550000001",
            "voice_url": "https://example.test/twiml",
            "status_callback_url": "https://example.test/status",
        },
        timeouts={"call": 20},
    )


def test_twilio_provider_initialization_from_generic_config():
    provider = TwilioProvider(config=_config(), client=FakeTwilioClient())

    assert provider.settings.account_sid == "AC123"
    assert provider.settings.auth_token == "token"
    assert provider.settings.phone_number == "+15550000001"
    assert provider.settings.timeout_seconds == 20


def test_twilio_provider_outbound_call_uses_client_and_returns_generic_session():
    client = FakeTwilioClient()
    provider = TwilioProvider(config=_config(), client=client)

    session = provider.start_outbound_call(to="+15550000002")

    assert session.direction == CallDirection.outbound
    assert session.provider_name == "twilio"
    assert session.provider_call_id == "CA123"
    assert session.status == CallStatus.created
    assert client.calls.created[0]["to"] == "+15550000002"
    assert client.calls.created[0]["from_"] == "+15550000001"
    assert client.calls.created[0]["status_callback"] == "https://example.test/status"
    assert provider.fetch_events(session)


def test_twilio_provider_status_end_recording_and_download():
    client = FakeTwilioClient()
    provider = TwilioProvider(config=_config(), client=client)
    session = provider.start_outbound_call(to="+15550000002")

    status = provider.get_call_status(session)
    ended = provider.end_call(session)
    recording = provider.fetch_recording(session)
    downloaded = provider.download_recording(recording, "artifacts/call/audio")

    assert status == CallStatus.in_progress
    assert ended.status == CallStatus.completed
    assert recording.provider_recording_id == "RE123"
    assert downloaded.path == "artifacts/call/audio/RE123.wav"


def test_twilio_provider_prepare_inbound_session():
    provider = TwilioProvider(config=_config(), client=FakeTwilioClient())

    session = provider.prepare_inbound_call(expected_from="+15550000003")

    assert session.direction == CallDirection.inbound
    assert session.status == CallStatus.prepared
    assert session.from_number == "+15550000003"
    assert session.to_number == "+15550000001"
    assert session.provider_metadata["webhook_secret_configured"] is False


def test_twilio_provider_ingests_status_webhook():
    provider = TwilioProvider(config=_config(), client=FakeTwilioClient())
    session = provider.prepare_inbound_call(expected_from="+15550000003")

    updated = provider.ingest_status_webhook(
        session,
        {"CallSid": "CA999", "AccountSid": "AC123", "CallStatus": "ringing"},
    )

    assert updated.status == CallStatus.ringing
    assert updated.provider_metadata["call_sid"] == "CA999"
    assert provider.fetch_events(updated)[-1].data["status"] == "ringing"


def test_provider_factory_still_supports_mock_and_passes_config_to_twilio():
    registry = ProviderRegistry()
    registry.register("mock", MockCallProvider)
    registry.register("twilio", TwilioProvider)
    factory = ProviderFactory(registry)

    mock = factory.create(CallingProviderConfig(provider_name="mock"))
    twilio = factory.create(_config())

    assert isinstance(mock, MockCallProvider)
    assert isinstance(twilio, TwilioProvider)
    assert twilio.settings.account_sid == "AC123"
