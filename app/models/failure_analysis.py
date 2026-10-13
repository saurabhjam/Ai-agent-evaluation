"""Reusable failure analysis models for enterprise evaluation reporting."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class FailureAnalysis(BaseModel):
    """
    Structured explanation for a failed or degraded evaluation finding.

    This is intentionally data-only. Generation and scoring of failure analysis
    is handled by later phases so existing evaluation behavior remains unchanged.
    """

    failure_id: str = Field(default_factory=lambda: str(uuid4()))
    category: Optional[str] = None
    source: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metric_name: str
    status: str
    severity: str
    reason: str
    failure_summary: Optional[str] = None
    expected: Optional[Any] = None
    actual: Optional[Any] = None
    root_cause: Optional[str] = None
    business_impact: Optional[str] = None
    recommendation: Optional[str] = None
    conversation_turn: Optional[int] = None
    conversation_message_id: Optional[str] = None
    conversation_snippet: Optional[list[dict[str, Any]]] = None
    evidence: list[Any] = Field(default_factory=list)
    technical_details: dict[str, Any] = Field(default_factory=dict)
