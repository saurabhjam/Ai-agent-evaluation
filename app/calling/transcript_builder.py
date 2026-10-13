"""Build normalized call transcripts from raw transcript sources."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.calling.conversation_evidence import ConversationEvidence
from app.calling.conversation_normalizer import ConversationNormalizer
from app.calling.evidence_builder import EvidenceBuilder
from app.calling.models import CallSession, CallTranscriptTurn, RawCallTranscript
from app.calling.speaker_mapper import SpeakerMapper
from app.calling.transcript_validator import TranscriptValidator
from app.calling.transcription import RawTranscript, RawTranscriptSegment
from app.models.conversation import NormalizedConversation


@dataclass
class TranscriptBuilder:
    """Builds validated normalized transcripts and conversations."""

    speaker_mapper: SpeakerMapper = field(default_factory=SpeakerMapper)
    validator: TranscriptValidator = field(default_factory=TranscriptValidator)
    evidence_builder: EvidenceBuilder = field(default_factory=EvidenceBuilder)
    conversation_normalizer: ConversationNormalizer = field(default_factory=ConversationNormalizer)

    def build_transcript(
        self,
        *,
        session_id: str,
        run_id: str,
        raw_transcript: RawTranscript,
    ) -> RawCallTranscript:
        """Build and validate a RawCallTranscript."""
        turns = [
            self._segment_to_turn(segment, index)
            for index, segment in enumerate(raw_transcript.segments)
        ]
        transcript = RawCallTranscript(
            session_id=session_id,
            run_id=run_id,
            turns=turns,
            source=raw_transcript.source,
            metadata={
                "provider_name": raw_transcript.provider_name,
                "audio_metadata": raw_transcript.audio_metadata.model_dump(mode="json")
                if raw_transcript.audio_metadata
                else None,
                **raw_transcript.metadata,
            },
        )
        self.validator.validate(transcript)
        return transcript

    def build_evidence(
        self,
        *,
        session: CallSession,
        raw_transcript: RawTranscript,
        rag_context: list[str] | None = None,
    ) -> ConversationEvidence:
        """Build ConversationEvidence through the existing EvidenceBuilder."""
        transcript = self.build_transcript(
            session_id=session.session_id,
            run_id=session.run_id,
            raw_transcript=raw_transcript,
        )
        return self.evidence_builder.build(
            session=session,
            transcript=transcript,
            rag_context=rag_context,
        )

    def build_conversation(
        self,
        *,
        session: CallSession,
        raw_transcript: RawTranscript,
        scenario_id: str | None = None,
        rag_context: list[str] | None = None,
        rag_config: dict | None = None,
    ) -> NormalizedConversation:
        """Build the final NormalizedConversation used by evaluation."""
        evidence = self.build_evidence(
            session=session,
            raw_transcript=raw_transcript,
            rag_context=rag_context,
        )
        return self.conversation_normalizer.normalize(evidence, scenario_id=scenario_id, rag_config=rag_config)

    def _segment_to_turn(self, segment: RawTranscriptSegment, index: int) -> CallTranscriptTurn:
        speaker = self.speaker_mapper.map(segment.speaker)
        return CallTranscriptTurn(
            speaker=speaker,
            text=segment.text,
            turn_index=index,
            start_time=segment.start_time,
            end_time=segment.end_time,
            confidence=segment.confidence,
            metadata=segment.metadata,
        )
