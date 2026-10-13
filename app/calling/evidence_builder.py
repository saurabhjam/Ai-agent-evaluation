"""Build ConversationEvidence from calling session outputs."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.calling.artifact_collector import ArtifactCollector
from app.calling.conversation_evidence import ConversationEvidence, EvidenceArtifact
from app.calling.models import CallEvent, CallRecording, CallSession, RawCallTranscript


@dataclass
class EvidenceBuilder:
    """Combines session, events, recordings, transcript, and artifacts."""

    artifact_collector: ArtifactCollector = field(default_factory=ArtifactCollector)

    def build(
        self,
        *,
        session: CallSession,
        events: list[CallEvent] | None = None,
        recordings: list[CallRecording] | None = None,
        transcript: RawCallTranscript | None = None,
        artifacts: list[EvidenceArtifact] | None = None,
        rag_context: list[str] | None = None,
    ) -> ConversationEvidence:
        """Create provider-neutral conversation evidence."""
        return self.artifact_collector.collect(
            session=session,
            transcript=transcript,
            events=events,
            recordings=recordings,
            artifacts=artifacts,
            rag_context=rag_context,
        )
