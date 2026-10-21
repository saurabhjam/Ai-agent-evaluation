from __future__ import annotations

from app.calling.config import CallingProviderConfig
from app.calling.execution_context import CallingExecutionContext
from app.calling.execution_events import CallingExecutionEventType
from app.calling.execution_pipeline import CallingExecutionPipeline, _select_transcript
from app.calling.execution_result import CallingExecutionStatus
from app.calling.models import (
    CallDirection,
    CallProvider,
    CallSession,
    CallStatus,
    CallTranscriptTurn,
    RawCallTranscript,
    TranscriptSpeaker,
)
from app.calling.provider_adapter import CallProviderAdapter, ProviderCapabilities
from app.calling.provider_resolver import ProviderResolver
from app.calling.provider_registry import ProviderRegistry
from app.calling.providers.mock import MockCallProvider
from app.schemas import AgentConfig, Persona, TestScenario


def _scenario() -> TestScenario:
    return TestScenario(
        scenario_id="calling-pipeline",
        agent=AgentConfig(channel="calling", adapter="mock"),
        persona=Persona(
            name="Ava",
            goal="Book an appointment for tomorrow morning",
            tone="polite",
        ),
        rag_context=["Appointments can be booked for tomorrow."],
    )


def test_calling_execution_pipeline_successful_execution():
    context = CallingExecutionContext(
        scenario=_scenario(),
        provider_config=CallingProviderConfig(provider_name="mock"),
    )

    result = CallingExecutionPipeline().execute(context)

    assert result.status == CallingExecutionStatus.completed
    assert result.success is True
    assert result.call_session.status == CallStatus.completed
    assert result.conversation_evidence is not None
    assert result.normalized_conversation.channel == "calling"
    assert result.normalized_conversation.retrieval_context == ["Appointments can be booked for tomorrow."]
    assert len(result.artifacts) == 2
    assert result.duration_seconds is not None
    assert [event.event_type for event in result.execution_events] == [
        CallingExecutionEventType.started,
        CallingExecutionEventType.connected,
        CallingExecutionEventType.in_progress,
        CallingExecutionEventType.completed,
    ]


def test_calling_execution_pipeline_provider_failure():
    context = CallingExecutionContext(
        scenario=_scenario(),
        provider_config=CallingProviderConfig(provider_name="missing"),
    )

    result = CallingExecutionPipeline(
        provider_resolver=ProviderResolver(registry=ProviderRegistry())
    ).execute(context)

    assert result.status == CallingExecutionStatus.failed
    assert result.success is False
    assert result.call_session is None
    assert result.normalized_conversation is None
    assert result.error
    assert result.execution_events[-1].event_type == CallingExecutionEventType.failed


class FailingSessionProvider(MockCallProvider):
    def end_call(self, session):
        return self.simulate_failed(session, reason="session failure")


def test_calling_execution_pipeline_session_failure():
    registry = ProviderRegistry()
    registry.register("failing", FailingSessionProvider)
    context = CallingExecutionContext(
        scenario=_scenario(),
        provider_config=CallingProviderConfig(provider_name="failing"),
    )

    result = CallingExecutionPipeline(
        provider_resolver=ProviderResolver(registry=registry)
    ).execute(context)

    assert result.status == CallingExecutionStatus.failed
    assert result.call_session.status == CallStatus.failed
    assert result.conversation_evidence is not None
    assert result.normalized_conversation is not None
    assert result.error == "Call session ended with status failed."
    assert result.execution_events[-1].event_type == CallingExecutionEventType.failed


def test_calling_execution_pipeline_inbound_success():
    context = CallingExecutionContext(scenario=_scenario())

    result = CallingExecutionPipeline().execute(context, direction=CallDirection.inbound)

    assert result.status == CallingExecutionStatus.completed
    assert result.call_session.direction == CallDirection.inbound
    assert result.normalized_conversation.metadata["direction"] == "inbound"


class LifecycleProvider(CallProviderAdapter):
    wait_calls = 0

    def __init__(self, config):
        self.config = config

    def get_capabilities(self):
        return ProviderCapabilities(
            supports_outbound_sessions=True,
            supports_provider_transcript=True,
            preferred_transcript_source="provider",
        )

    def start_outbound_call(self, *, to, from_=None, metadata=None):
        return CallSession(
            direction=CallDirection.outbound,
            provider=CallProvider.custom,
            provider_name="lifecycle",
            provider_call_id="call-lifecycle",
            status=CallStatus.in_progress,
        )

    def prepare_inbound_call(self, *, expected_from=None, metadata=None):
        raise NotImplementedError

    def get_call_status(self, session):
        return session.status

    def wait_for_completion(self, session, **kwargs):
        type(self).wait_calls += 1
        return session.model_copy(update={"status": CallStatus.completed})

    def end_call(self, session):
        return session

    def fetch_recording(self, session):
        return None

    def fetch_events(self, session):
        return []

    def fetch_transcript(self, session):
        return RawCallTranscript(
            session_id=session.session_id,
            run_id=session.run_id,
            source="provider",
            turns=[
                CallTranscriptTurn(
                    speaker=TranscriptSpeaker.agent,
                    text="Hello",
                    turn_index=0,
                )
            ],
        )

    def download_recording(self, recording, destination_dir):
        return recording


def test_calling_execution_pipeline_uses_provider_completion_contract():
    registry = ProviderRegistry()
    registry.register("lifecycle", LifecycleProvider)
    context = CallingExecutionContext(
        scenario=_scenario(),
        provider_config=CallingProviderConfig(provider_name="lifecycle"),
    )
    LifecycleProvider.wait_calls = 0

    result = CallingExecutionPipeline(
        provider_resolver=ProviderResolver(registry=registry)
    ).execute(context)

    assert result.status == CallingExecutionStatus.completed
    assert result.call_session.status == CallStatus.completed
    assert LifecycleProvider.wait_calls == 1


class TranscriptProvider:
    def __init__(self, transcript):
        self.transcript = transcript
        self.fetch_calls = 0

    def fetch_transcript(self, session):
        self.fetch_calls += 1
        return self.transcript


def _call_session() -> CallSession:
    return CallSession(
        direction=CallDirection.outbound,
        provider=CallProvider.custom,
        provider_name="test",
        provider_call_id="call-123",
        status=CallStatus.completed,
    )


def _transcript(source: str, text: str) -> RawCallTranscript:
    return RawCallTranscript(
        session_id="session-123",
        run_id="run-123",
        source=source,
        turns=[
            CallTranscriptTurn(
                speaker=TranscriptSpeaker.agent,
                text=text,
                turn_index=0,
            )
        ],
    )


def test_transcript_selection_prefers_provider_transcript_when_advertised():
    provider_transcript = _transcript("provider", "Provider assistant response")
    transport_transcript = _transcript("transport", "Local STT response")
    provider = TranscriptProvider(provider_transcript)

    selected = _select_transcript(
        provider=provider,
        capabilities=ProviderCapabilities(
            supports_provider_transcript=True,
            preferred_transcript_source="provider",
        ),
        session=_call_session(),
        transport_transcript=transport_transcript,
    )

    assert selected is provider_transcript
    assert provider.fetch_calls == 1


def test_transcript_selection_falls_back_to_transport_when_provider_unavailable():
    transport_transcript = _transcript("transport", "Local STT response")
    provider = TranscriptProvider(None)

    selected = _select_transcript(
        provider=provider,
        capabilities=ProviderCapabilities(
            supports_provider_transcript=True,
            preferred_transcript_source="provider",
        ),
        session=_call_session(),
        transport_transcript=transport_transcript,
    )

    assert selected is transport_transcript
    assert provider.fetch_calls == 1


def test_transcript_selection_keeps_existing_transport_first_behavior():
    provider_transcript = _transcript("provider", "Provider assistant response")
    transport_transcript = _transcript("transport", "Local STT response")
    provider = TranscriptProvider(provider_transcript)

    selected = _select_transcript(
        provider=provider,
        capabilities=ProviderCapabilities(),
        session=_call_session(),
        transport_transcript=transport_transcript,
    )

    assert selected is transport_transcript
    assert provider.fetch_calls == 0
