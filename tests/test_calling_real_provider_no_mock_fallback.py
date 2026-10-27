from __future__ import annotations

import pytest

from app.calling.config import CallingProviderConfig
from app.calling.execution_context import CallingExecutionContext
from app.calling.execution_pipeline import CallingExecutionPipeline
from app.calling.execution_result import CallingExecutionStatus
from app.calling.models import (
    CallDirection,
    CallEvent,
    CallRecording,
    CallSession,
    CallStatus,
    CallTranscriptTurn,
    NormalizedCallTranscript,
    TranscriptSpeaker,
)
from app.calling.provider_adapter import CallProviderAdapter, ProviderCapabilities
from app.calling.provider_resolver import ProviderResolver
from app.calling.provider_registry import ProviderRegistry
from app.calling.providers.mock import MockCallProvider
from app.calling.providers.vapi import VapiProvider
from app.calling.runner import CallSessionRunner
from app.schemas import AgentConfig, Persona, TestScenario


@pytest.fixture(autouse=True)
def offline_provider_boundaries(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("offline provider unavailable")

    def unavailable_websocket(*args, **kwargs):
        raise RuntimeError("offline websocket unavailable")

    monkeypatch.setattr("app.calling.providers.vapi.requests.post", unavailable)
    monkeypatch.setattr("app.calling.providers.vapi.requests.get", unavailable)
    monkeypatch.setattr("app.calling.voice_transport._default_websocket_factory", lambda: unavailable_websocket)


def _scenario() -> TestScenario:
    return TestScenario(
        scenario_id="real-provider-no-mock",
        agent=AgentConfig(channel="calling", adapter="vapi"),
        persona=Persona(name="Rahul", goal="Book a dental appointment", tone="polite"),
    )


def _context(provider_name: str, **config_kwargs) -> CallingExecutionContext:
    return CallingExecutionContext(
        scenario=_scenario(),
        provider_config=CallingProviderConfig(provider_name=provider_name, **config_kwargs),
    )


def test_configured_vapi_resolves_vapi_provider():
    provider = ProviderResolver().resolve(
        CallingProviderConfig(
            provider_name="vapi",
            credentials={"api_key": "test-key"},
            settings={"assistant_id": "assistant-id", "phone_number_id": "phone-id"},
        )
    )

    assert isinstance(provider, VapiProvider)


def test_configured_vapi_never_calls_run_mock_call(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("run_mock_call must not be used for vapi")

    monkeypatch.setattr(CallSessionRunner, "run_mock_call", fail_if_called)

    result = CallingExecutionPipeline().execute(
        _context(
            "vapi",
            credentials={"api_key": "test-key"},
            settings={"assistant_id": "assistant-id", "phone_number_id": "phone-id"},
        ),
        direction=CallDirection.inbound,
    )

    assert result.status == CallingExecutionStatus.failed
    assert "offline provider unavailable" in result.error


def test_configured_vapi_never_calls_build_mock_transcript(monkeypatch):
    import app.calling.runner as runner_module

    def fail_if_called(*args, **kwargs):
        raise AssertionError("build_mock_transcript must not be used for vapi")

    monkeypatch.setattr(runner_module, "build_mock_transcript", fail_if_called)

    result = CallingExecutionPipeline().execute(
        _context(
            "vapi",
            credentials={"api_key": "test-key"},
            settings={"assistant_id": "assistant-id", "phone_number_id": "phone-id"},
        ),
        direction=CallDirection.inbound,
    )

    assert result.status == CallingExecutionStatus.failed
    assert "offline provider unavailable" in result.error


def test_configured_vapi_provider_failure_returns_error_not_mock_result(monkeypatch):
    def fail_post(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("app.calling.providers.vapi.requests.post", fail_post)

    result = CallingExecutionPipeline().execute(
        _context(
            "vapi",
            credentials={"api_key": "test-key"},
            settings={"assistant_id": "assistant-id", "phone_number_id": "phone-id"},
        )
    )

    assert result.status == CallingExecutionStatus.failed
    assert result.call_session is None
    assert "provider unavailable" in result.error


def test_configured_twilio_never_silently_falls_back_to_mock():
    result = CallingExecutionPipeline().execute(_context("twilio"))

    assert result.status == CallingExecutionStatus.failed
    assert result.call_session is None
    assert "mock" not in (result.error or "").lower()


def test_provider_mock_still_uses_mock_runner():
    result = CallingExecutionPipeline().execute(_context("mock"))

    assert result.status == CallingExecutionStatus.completed
    assert result.call_session.provider_name == "mock"
    assert result.normalized_conversation.messages


class _VapiResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "id": "real-vapi-call-id",
            "transport": {"websocketCallUrl": "wss://example.test/call"},
        }


def test_vapi_outbound_requires_real_transcript(monkeypatch):
    monkeypatch.setattr(
        "app.calling.providers.vapi.requests.post",
        lambda *args, **kwargs: _VapiResponse(),
    )

    result = CallingExecutionPipeline().execute(
        _context(
            "vapi",
            credentials={"api_key": "test-key"},
            settings={"assistant_id": "assistant-id", "phone_number_id": "phone-id"},
        )
    )

    assert result.status == CallingExecutionStatus.failed
    assert result.call_session is None
    assert "websocket" in result.error.lower() or "tts" in result.error.lower()


class TranscriptProvider(CallProviderAdapter):
    def start_outbound_call(self, *, to, from_=None, metadata=None):
        return CallSession(
            direction=CallDirection.outbound,
            status=CallStatus.completed,
            provider_name="vapi",
            provider_call_id="real-vapi-call-id",
            metadata=metadata or {},
        )

    def prepare_inbound_call(self, *, expected_from=None, metadata=None):
        raise NotImplementedError("not used")

    def get_call_status(self, session):
        return CallStatus.completed

    def end_call(self, session):
        return session

    def fetch_recording(self, session):
        return None

    def fetch_events(self, session) -> list[CallEvent]:
        return []

    def download_recording(self, recording: CallRecording, destination_dir: str) -> CallRecording:
        return recording

    def fetch_transcript(self, session):
        return NormalizedCallTranscript(
            session_id=session.session_id,
            run_id=session.run_id,
            source="provider",
            metadata={"provider": "vapi"},
            turns=[
                CallTranscriptTurn(
                    speaker=TranscriptSpeaker.customer,
                    text="I need a dental appointment.",
                    turn_index=0,
                ),
                CallTranscriptTurn(
                    speaker=TranscriptSpeaker.agent,
                    text="I can help with that.",
                    turn_index=1,
                ),
            ],
        )


def test_provider_runtime_matches_configured_real_provider():
    registry = ProviderRegistry()
    registry.register("vapi", TranscriptProvider)

    result = CallingExecutionPipeline(
        provider_resolver=ProviderResolver(registry=registry)
    ).execute(_context("vapi"))

    assert result.status == CallingExecutionStatus.completed
    assert result.call_session.provider_name == "vapi"
    assert result.call_session.provider_call_id == "real-vapi-call-id"


def test_mock_recording_is_impossible_for_real_provider_runs():
    registry = ProviderRegistry()
    registry.register("vapi", MockCallProvider)

    result = CallingExecutionPipeline(
        provider_resolver=ProviderResolver(registry=registry)
    ).execute(_context("vapi"))

    assert result.status == CallingExecutionStatus.failed
    assert "resolved to mock runtime" in result.error


def test_unsupported_real_inbound_returns_explicit_error_instead_of_mock():
    class UnsupportedInboundProvider(TranscriptProvider):
        def get_capabilities(self):
            return ProviderCapabilities(supports_outbound_sessions=True)

    registry = ProviderRegistry()
    registry.register("custom", UnsupportedInboundProvider)

    result = CallingExecutionPipeline(
        provider_resolver=ProviderResolver(registry=registry)
    ).execute(_context("custom"), direction=CallDirection.inbound)

    assert result.status == CallingExecutionStatus.failed
    assert result.call_session is None
    assert "Advertised connection methods" in result.error
    assert "direct inbound session" in result.error


def test_existing_mock_lifecycle_remains_unchanged():
    result = CallingExecutionPipeline().execute(_context("mock"))

    assert result.call_session.status == CallStatus.completed
    assert result.conversation_evidence.provider_name == "mock"
    assert result.normalized_conversation.channel == "calling"
