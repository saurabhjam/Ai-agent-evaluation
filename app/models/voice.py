"""
Universal Voice Models — vendor-neutral Pydantic types.

These models represent the normalized evidence produced by any VoiceAdapter,
regardless of the underlying phone provider, STT engine, or TTS engine.

They are the voice-channel equivalent of:
  app/models/conversation.py   ->  chat channel evidence
  app/models/voice.py          ->  voice channel evidence

The two representations share the same evaluation core and DeepEval
conversion boundary (see app/voice/converter.py).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid

from pydantic import BaseModel, Field

from app.models.conversation import RAGEvidence


# ---------------------------------------------------------------------------
# Enums / constants
# ---------------------------------------------------------------------------

class Speaker(str, Enum):
    """Identifies who produced a turn in the conversation."""
    user = "user"       # human caller / simulated user
    agent = "agent"     # AI voice agent under test
    system = "system"   # framework-generated entries (e.g. call start/end)


class SessionStatus(str, Enum):
    """Lifecycle state of a voice call session."""
    pending = "pending"
    active = "active"
    completed = "completed"
    failed = "failed"
    timed_out = "timed_out"


class VoiceEventType(str, Enum):
    """
    Normalised event vocabulary.  Vendor adapters must map their own
    event names onto one of these values before storing.
    """
    call_started = "call_started"
    call_ended = "call_ended"
    speech_started = "speech_started"
    speech_ended = "speech_ended"
    response_started = "response_started"
    response_completed = "response_completed"
    interruption = "interruption"
    silence_detected = "silence_detected"
    error = "error"
    custom = "custom"


# ---------------------------------------------------------------------------
# Core voice turn model
# ---------------------------------------------------------------------------

class VoiceTurn(BaseModel):
    """
    A single speaker turn (utterance) in the conversation.

    Both user and agent utterances are represented as VoiceTurn instances.
    The STT transcript (text) is the normalised string form; the raw
    audio is referenced via audio_path if it was recorded locally.
    """
    turn_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    speaker: Speaker
    text: str = ""
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    latency_ms: Optional[float] = None
    audio_path: Optional[str] = None
    interrupted: bool = False
    confidence: Optional[float] = None
    metadata: Optional[dict[str, Any]] = None
    rag_evidence: Optional[RAGEvidence] = None


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------

class VoiceEvent(BaseModel):
    """
    A discrete, timestamped event that occurred during the call.

    Adapters translate their native webhooks / callbacks into VoiceEvent
    instances using the normalised VoiceEventType vocabulary.
    """
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: VoiceEventType
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    data: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Tool call / result models
# ---------------------------------------------------------------------------

class ToolCall(BaseModel):
    """Records a tool invocation made by the voice agent."""
    tool_call_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ToolResult(BaseModel):
    """Records the result returned by a tool invoked by the voice agent."""
    tool_call_id: str = ""
    tool_name: str
    result: Any = None
    success: bool = True
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    latency_ms: Optional[float] = None


# ---------------------------------------------------------------------------
# Handoff model
# ---------------------------------------------------------------------------

class HandoffEvent(BaseModel):
    """
    Records a live-agent (or queue) handoff requested by the AI agent.

    Not all voice scenarios will produce handoffs; this is optional evidence.
    """
    handoff_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    requested: bool = False
    started: bool = False
    completed: bool = False
    destination: Optional[str] = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Session model
# ---------------------------------------------------------------------------

class VoiceSession(BaseModel):
    """
    Top-level metadata about a single voice call session.

    call_id is the identifier used by the underlying provider (or a
    framework-generated UUID for local/fake adapters).
    """
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    call_id: Optional[str] = None
    channel: str = "voice"
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    status: SessionStatus = SessionStatus.pending
    metadata: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Top-level normalized voice conversation
# ---------------------------------------------------------------------------

class VoiceConversation(BaseModel):
    """
    The complete, normalised evidence produced by a VoiceAdapter after a call.

    This is the voice-channel equivalent of NormalizedConversation and feeds
    into the shared evaluation core via the voice->chat converter in
    app/voice/converter.py.

    All fields contain vendor-neutral Python types only.
    """
    session: VoiceSession
    turns: list[VoiceTurn] = Field(default_factory=list)
    events: list[VoiceEvent] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    handoff_events: list[HandoffEvent] = Field(default_factory=list)
    metadata: Optional[dict[str, Any]] = None

    # ------------------------------------------------------------------ #
    # Convenience helpers                                                  #
    # ------------------------------------------------------------------ #

    def user_turns(self) -> list[VoiceTurn]:
        """Return only turns produced by the user / simulated caller."""
        return [t for t in self.turns if t.speaker == Speaker.user]

    def agent_turns(self) -> list[VoiceTurn]:
        """Return only turns produced by the AI agent under test."""
        return [t for t in self.turns if t.speaker == Speaker.agent]

    def interruptions(self) -> list[VoiceTurn]:
        """Return turns where the user interrupted the agent."""
        return [t for t in self.turns if t.interrupted]

    def average_agent_latency_ms(self) -> Optional[float]:
        """Average agent response latency across all agent turns, or None."""
        agent_latencies = [
            t.latency_ms
            for t in self.agent_turns()
            if t.latency_ms is not None
        ]
        if not agent_latencies:
            return None
        return sum(agent_latencies) / len(agent_latencies)

    def duration_seconds(self) -> Optional[float]:
        """Wall-clock call duration in seconds, or None if timestamps missing."""
        if self.session.started_at and self.session.ended_at:
            try:
                start = datetime.fromisoformat(self.session.started_at)
                end = datetime.fromisoformat(self.session.ended_at)
                return (end - start).total_seconds()
            except (ValueError, TypeError):
                return None
        return None
