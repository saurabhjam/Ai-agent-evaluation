"""Evaluation context for calling execution results."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.calling.conversation_evidence import EvidenceArtifact
from app.models.conversation import NormalizedConversation


class CallingEvaluationContext(BaseModel):
    """Metadata passed from calling runtime into the evaluation bridge."""

    run_id: str
    scenario_id: str
    provider: Optional[str] = None
    call_id: Optional[str] = None
    conversation: NormalizedConversation
    artifacts: list[EvidenceArtifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    rag_context: Optional[list[str]] = None
