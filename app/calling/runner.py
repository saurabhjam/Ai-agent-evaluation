"""Generic in-memory runner for Phase 2 calling lifecycle simulation."""

from __future__ import annotations

from dataclasses import dataclass

from typing import Optional

from app.calling.config import CallingProviderConfig, default_mock_provider_config
from app.calling.conversation_evidence import ConversationEvidence, EvidenceArtifact
from app.calling.conversation_normalizer import ConversationNormalizer
from app.calling.evidence_builder import EvidenceBuilder
from app.calling.models import (
    CallingExecutionResult,
    CallArtifact,
    CallArtifactType,
    CallDirection,
    CallEventType,
    CallSession,
    CallStatus,
    CallTranscriptTurn,
    RawCallTranscript,
    TranscriptSpeaker,
)
from app.calling.normalizer import call_transcript_to_normalized_conversation
from app.calling.provider_adapter import CallProviderAdapter
from app.calling.provider_resolver import ProviderResolver
from app.models.conversation import NormalizedConversation


@dataclass
class CallingEvaluationRunner:
    """Runs a deterministic call lifecycle simulation to normalized evidence."""

    provider_adapter: Optional[CallProviderAdapter] = None
    provider_resolver: Optional[ProviderResolver] = None
    provider_config: Optional[CallingProviderConfig] = None

    def build_pending_result(self, session: CallSession) -> CallingExecutionResult:
        """Create an unevaluated evidence result for a prepared session."""
        return CallingExecutionResult(success=True, session=session)

    def run_mock_call(
        self,
        *,
        to: str = "+15550000002",
        from_: str = "+15550000001",
        scenario_id: Optional[str] = None,
        direction: CallDirection = CallDirection.outbound,
        retrieval_context: Optional[list[str]] = None,
        rag_config: Optional[dict] = None,
    ) -> "CallSessionRunnerResult":
        """
        Simulate a full call lifecycle and return normalized evidence.

        This method does not invoke DeepEval, EvaluationService, APIs, STT, real
        calls, webhooks, or recordings.
        """
        provider_adapter = self._resolve_provider()
        if direction == CallDirection.outbound:
            session = provider_adapter.start_outbound_call(
                to=to,
                from_=from_,
                metadata={"scenario_id": scenario_id} if scenario_id else None,
            )
        else:
            session = provider_adapter.prepare_inbound_call(
                expected_from=from_,
                metadata={"scenario_id": scenario_id} if scenario_id else None,
            )
            if hasattr(provider_adapter, "simulate_inbound_connected"):
                session = provider_adapter.simulate_inbound_connected(session)

        if hasattr(provider_adapter, "simulate_conversation_started"):
            session = provider_adapter.simulate_conversation_started(session)
        session = provider_adapter.end_call(session)

        transcript = build_mock_transcript(session)
        events = provider_adapter.fetch_events(session)
        recording = provider_adapter.fetch_recording(session)
        evidence_artifacts: list[EvidenceArtifact] = [
            EvidenceArtifact(
                session_id=session.session_id,
                name="transcript.json",
                artifact_type=CallArtifactType.transcript.value,
                path=f"artifacts/call/transcript/{session.run_id}.json",
                content_type="application/json",
                provider=session.provider,
                provider_name=session.provider_name,
                metadata={"placeholder": True},
            ),
            EvidenceArtifact(
                session_id=session.session_id,
                name="events.json",
                artifact_type=CallArtifactType.events.value,
                path=f"artifacts/call/events/{session.run_id}.json",
                content_type="application/json",
                provider=session.provider,
                provider_name=session.provider_name,
                metadata={"placeholder": True},
            ),
        ]
        recordings = [recording] if recording else []
        evidence = EvidenceBuilder().build(
            session=session,
            events=events,
            recordings=recordings,
            transcript=transcript,
            artifacts=evidence_artifacts,
            rag_context=retrieval_context,
        )
        normalized = ConversationNormalizer().normalize(
            evidence,
            scenario_id=scenario_id,
            rag_config=rag_config,
        )

        execution_result = CallingExecutionResult(
            success=session.status == CallStatus.completed,
            session=session,
            transcript=transcript,
            artifacts=[_evidence_artifact_to_call_artifact(artifact) for artifact in evidence.attachments]
            + recordings,
            events=events,
            metadata={"evidence_id": evidence.evidence_id},
        )
        return CallSessionRunnerResult(
            execution_result=execution_result,
            conversation_evidence=evidence,
            normalized_conversation=normalized,
        )

    def _resolve_provider(self) -> CallProviderAdapter:
        """Resolve the provider through the Phase 3 provider infrastructure."""
        if self.provider_adapter is not None:
            return self.provider_adapter
        resolver = self.provider_resolver or ProviderResolver()
        config = self.provider_config or default_mock_provider_config()
        return resolver.resolve(config)


@dataclass(frozen=True)
class CallSessionRunnerResult:
    """Evidence produced by the Phase 2 runner."""

    execution_result: CallingExecutionResult
    conversation_evidence: ConversationEvidence
    normalized_conversation: NormalizedConversation


class CallSessionRunner(CallingEvaluationRunner):
    """Named Phase 2 runner for generic call sessions."""


def build_mock_transcript(session: CallSession) -> RawCallTranscript:
    """Create a deterministic mock transcript for lifecycle tests."""
    turns = [
        CallTranscriptTurn(
            speaker=TranscriptSpeaker.customer,
            text="Hello, I'd like to book an appointment.",
            turn_index=0,
            confidence=1.0,
        ),
        CallTranscriptTurn(
            speaker=TranscriptSpeaker.agent,
            text="Sure, what date works for you?",
            turn_index=1,
            confidence=1.0,
        ),
        CallTranscriptTurn(
            speaker=TranscriptSpeaker.customer,
            text="Tomorrow morning.",
            turn_index=2,
            confidence=1.0,
        ),
        CallTranscriptTurn(
            speaker=TranscriptSpeaker.agent,
            text="Done.",
            turn_index=3,
            confidence=1.0,
        ),
    ]
    return RawCallTranscript(
        session_id=session.session_id,
        run_id=session.run_id,
        turns=turns,
        language="en",
        source="mock_provider",
        metadata={
            "provider": session.provider.value,
            "provider_name": session.provider_name,
            "provider_call_id": session.provider_call_id,
            "direction": session.direction.value,
            "event_source": CallEventType.transcript_available.value,
        },
    )


def _evidence_artifact_to_call_artifact(artifact: EvidenceArtifact) -> CallArtifact:
    """Convert evidence artifact metadata to the Phase 1 result artifact shape."""
    return CallArtifact(
        artifact_id=artifact.artifact_id,
        session_id=artifact.session_id,
        artifact_type=CallArtifactType(artifact.artifact_type),
        provider=artifact.provider,
        provider_name=artifact.provider_name,
        path=artifact.path,
        remote_url=artifact.remote_url,
        content_type=artifact.content_type,
        created_at=artifact.created_at,
        metadata=artifact.metadata,
    )
