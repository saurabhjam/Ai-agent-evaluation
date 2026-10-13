"""Collect provider outputs into conversation evidence artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.calling.artifact_store import ArtifactStore
from app.calling.conversation_evidence import ConversationEvidence, EvidenceArtifact
from app.calling.models import CallEvent, CallRecording, CallSession, RawCallTranscript


@dataclass
class ArtifactCollector:
    """Collects provider-neutral outputs and stores artifact metadata."""

    artifact_store: ArtifactStore = field(default_factory=ArtifactStore)

    def collect(
        self,
        *,
        session: CallSession,
        transcript: RawCallTranscript | None = None,
        events: list[CallEvent] | None = None,
        recordings: list[CallRecording] | None = None,
        artifacts: list[EvidenceArtifact] | None = None,
        rag_context: list[str] | None = None,
    ) -> ConversationEvidence:
        """Build evidence from provider outputs and store artifact metadata."""
        stored_artifacts = [self.artifact_store.store(artifact) for artifact in artifacts or []]
        return ConversationEvidence(
            session_id=session.session_id,
            run_id=session.run_id,
            provider=session.provider,
            provider_name=session.provider_name,
            provider_call_id=session.provider_call_id,
            provider_metadata=session.provider_metadata,
            recordings=recordings or [],
            transcript=transcript,
            transcript_turns=list(transcript.turns) if transcript else [],
            events=events or [],
            attachments=stored_artifacts,
            rag_context=rag_context,
            started_at=session.started_at,
            connected_at=session.connected_at,
            ended_at=session.ended_at,
            metadata={
                "direction": session.direction.value,
                **session.metadata,
            },
        )
