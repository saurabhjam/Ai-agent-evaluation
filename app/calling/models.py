"""
Vendor-neutral models for AI Calling Agent Evaluation.

These types describe call evidence only. They do not dial providers, run STT,
or evaluate metrics. The calling subsystem hands normalized evidence to the
existing evaluation engine through app.calling.normalizer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


class CallDirection(str, Enum):
    """Whether EvalForge initiated the call or received it."""

    inbound = "inbound"
    outbound = "outbound"


class CallStatus(str, Enum):
    """Vendor-neutral call lifecycle states."""

    created = "created"
    pending = "pending"
    prepared = "prepared"
    dialing = "dialing"
    ringing = "ringing"
    connected = "connected"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    busy = "busy"
    no_answer = "no_answer"
    canceled = "canceled"
    cancelled = "cancelled"
    timed_out = "timed_out"
    transferred = "transferred"
    disconnected = "disconnected"
    error = "error"


class CallProvider(str, Enum):
    """Known provider families. Custom keeps the core provider-neutral."""

    custom = "custom"
    twilio = "twilio"
    livekit_sip = "livekit_sip"
    vapi = "vapi"
    retell = "retell"
    bland = "bland"
    custom_sip = "custom_sip"


class CallArtifactType(str, Enum):
    """Artifact types expected from a calling evaluation run."""

    audio = "audio"
    agent_audio = "agent_audio"
    customer_audio = "customer_audio"
    transcript = "transcript"
    events = "events"
    metrics = "metrics"
    backend = "backend"
    rag = "rag"
    deepeval = "deepeval"
    report = "report"


class CallEventType(str, Enum):
    """Normalized call event vocabulary."""

    call_created = "call_created"
    call_started = "call_started"
    inbound_prepared = "inbound_prepared"
    outbound_started = "outbound_started"
    call_ringing = "call_ringing"
    call_connected = "call_connected"
    call_in_progress = "call_in_progress"
    call_transferred = "call_transferred"
    call_hold = "call_hold"
    call_resumed = "call_resumed"
    call_completed = "call_completed"
    call_failed = "call_failed"
    call_ended = "call_ended"
    call_timeout = "call_timeout"
    call_busy = "call_busy"
    call_no_answer = "call_no_answer"
    call_cancelled = "call_cancelled"
    call_disconnected = "call_disconnected"
    recording_available = "recording_available"
    transcript_available = "transcript_available"
    error = "error"
    custom = "custom"


class TranscriptSpeaker(str, Enum):
    """Speakers in a normalized call transcript."""

    customer = "customer"
    agent = "agent"
    system = "system"


class ProviderConfig(BaseModel):
    """Provider-neutral configuration shell for future adapters."""

    provider: CallProvider = CallProvider.custom
    name: str = "custom"
    credentials_ref: Optional[str] = None
    settings: dict[str, Any] = Field(default_factory=dict)


class CallSession(BaseModel):
    """Lifecycle metadata for one calling-agent evaluation session."""

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scenario_id: Optional[str] = None
    provider: CallProvider = CallProvider.custom
    provider_name: Optional[str] = None
    provider_call_id: Optional[str] = None
    provider_recording_id: Optional[str] = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    direction: CallDirection
    status: CallStatus = CallStatus.pending
    from_number: Optional[str] = None
    to_number: Optional[str] = None
    started_at: Optional[str] = None
    connected_at: Optional[str] = None
    ended_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def mark_connected(self, timestamp: Optional[str] = None) -> "CallSession":
        """Return a copy marked as connected."""
        now = timestamp or utc_now_iso()
        return self.model_copy(
            update={
                "status": CallStatus.connected,
                "started_at": self.started_at or now,
                "connected_at": now,
            }
        )

    def mark_completed(self, timestamp: Optional[str] = None) -> "CallSession":
        """Return a copy marked as completed."""
        return self.model_copy(
            update={
                "status": CallStatus.completed,
                "ended_at": timestamp or utc_now_iso(),
            }
        )

    def mark_failed(self, reason: str, timestamp: Optional[str] = None) -> "CallSession":
        """Return a copy marked as failed with a failure reason."""
        metadata = {**self.metadata, "failure_reason": reason}
        return self.model_copy(
            update={
                "status": CallStatus.failed,
                "ended_at": timestamp or utc_now_iso(),
                "metadata": metadata,
            }
        )


class CallEvent(BaseModel):
    """A timestamped vendor-neutral event from a call provider."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    event_type: CallEventType
    timestamp: str = Field(default_factory=utc_now_iso)
    provider: CallProvider = CallProvider.custom
    provider_name: Optional[str] = None
    provider_event_id: Optional[str] = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)


class CallArtifact(BaseModel):
    """Metadata for an artifact produced by the calling pipeline."""

    artifact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    artifact_type: CallArtifactType
    provider: CallProvider = CallProvider.custom
    provider_name: Optional[str] = None
    path: Optional[str] = None
    remote_url: Optional[str] = None
    content_type: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CallRecording(CallArtifact):
    """Recording artifact metadata. No download behavior lives here."""

    artifact_type: CallArtifactType = CallArtifactType.audio
    recording_id: Optional[str] = None
    provider_recording_id: Optional[str] = None
    duration_seconds: Optional[float] = None
    channels: int = 1
    format: str = "wav"
    sample_rate: Optional[int] = None


class CallTranscriptTurn(BaseModel):
    """One transcript turn produced from a call recording or provider transcript."""

    speaker: TranscriptSpeaker
    text: str
    turn_index: int
    timestamp: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    confidence: Optional[float] = None
    audio_path: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawCallTranscript(BaseModel):
    """Provider-neutral raw call transcript before shared conversation normalization."""

    session_id: str
    run_id: str
    turns: list[CallTranscriptTurn] = Field(default_factory=list)
    language: Optional[str] = None
    source: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedCallTranscript(RawCallTranscript):
    """Backward-compatible name for existing calling transcript objects."""


class CallingExecutionResult(BaseModel):
    """
    Calling subsystem output.

    This stops at evidence collection. Evaluation remains the responsibility of
    the existing EvalForge evaluation engine after normalization.
    """

    success: bool
    session: CallSession
    transcript: Optional[RawCallTranscript] = None
    artifacts: list[CallArtifact] = Field(default_factory=list)
    events: list[CallEvent] = Field(default_factory=list)
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
