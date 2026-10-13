"""Universal conversation evidence model for calling providers."""

from __future__ import annotations

from typing import Any, Optional
import uuid

from pydantic import BaseModel, Field

from app.calling.models import (
    CallEvent,
    CallProvider,
    CallRecording,
    CallTranscriptTurn,
    NormalizedCallTranscript,
    RawCallTranscript,
    utc_now_iso,
)


class EvidenceArtifact(BaseModel):
    """Vendor-neutral artifact metadata for call evidence."""

    artifact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    name: str
    artifact_type: str
    path: Optional[str] = None
    remote_url: Optional[str] = None
    content_type: Optional[str] = None
    provider: CallProvider = CallProvider.custom
    provider_name: Optional[str] = None
    provider_artifact_id: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationEvidence(BaseModel):
    """
    Universal evidence envelope between calling providers and evaluation.

    Providers should fill this vendor-neutral model. The evaluation engine
    should see only NormalizedConversation after conversion.
    """

    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    run_id: str
    provider: CallProvider = CallProvider.custom
    provider_name: Optional[str] = None
    provider_call_id: Optional[str] = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    recordings: list[CallRecording] = Field(default_factory=list)
    transcript: Optional[RawCallTranscript] = None
    transcript_turns: list[CallTranscriptTurn] = Field(default_factory=list)
    events: list[CallEvent] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    logs: list[dict[str, Any]] = Field(default_factory=list)
    attachments: list[EvidenceArtifact] = Field(default_factory=list)
    backend_results: dict[str, Any] = Field(default_factory=dict)
    rag_context: Optional[list[str]] = None
    started_at: Optional[str] = None
    connected_at: Optional[str] = None
    ended_at: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def effective_transcript(self) -> RawCallTranscript:
        """Return transcript object, building one from transcript_turns if needed."""
        if self.transcript is not None:
            return self.transcript
        return RawCallTranscript(
            session_id=self.session_id,
            run_id=self.run_id,
            turns=self.transcript_turns,
            source="conversation_evidence",
            metadata={
                "provider": self.provider.value,
                "provider_name": self.provider_name,
                "provider_call_id": self.provider_call_id,
                **self.metadata,
            },
        )
