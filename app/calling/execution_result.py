"""Runtime execution result for AI Calling Agent Evaluation."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.calling.conversation_evidence import ConversationEvidence, EvidenceArtifact
from app.calling.execution_events import CallingExecutionEvent
from app.calling.models import CallSession
from app.models.conversation import NormalizedConversation


class CallingExecutionStatus(str, Enum):
    """Top-level runtime execution status."""

    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    timed_out = "timed_out"


class CallingExecutionResult(BaseModel):
    """Output of the Phase 5 calling runtime pipeline."""

    status: CallingExecutionStatus
    call_session: Optional[CallSession] = None
    conversation_evidence: Optional[ConversationEvidence] = None
    normalized_conversation: Optional[NormalizedConversation] = None
    artifacts: list[EvidenceArtifact] = Field(default_factory=list)
    execution_events: list[CallingExecutionEvent] = Field(default_factory=list)
    execution_metadata: dict[str, Any] = Field(default_factory=dict)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: Optional[float] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Return whether execution completed successfully."""
        return self.status == CallingExecutionStatus.completed
