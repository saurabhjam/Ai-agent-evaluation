"""Execution context for AI Calling Agent Evaluation runtime runs."""

from __future__ import annotations

from typing import Any, Optional
import uuid

from pydantic import BaseModel, Field

from app.calling.config import CallingProviderConfig, default_mock_provider_config
from app.calling.conversation_evidence import EvidenceArtifact
from app.calling.models import utc_now_iso
from app.schemas import TestScenario
from app.calling.voice_transport import VoiceTransportConfig


class CallingExecutionContext(BaseModel):
    """Input and runtime metadata for one calling execution."""

    scenario: TestScenario
    provider_config: CallingProviderConfig = Field(default_factory=default_mock_provider_config)
    voice_transport_config: Optional[VoiceTransportConfig] = None
    test_transport_config: Optional[VoiceTransportConfig] = Field(default=None, exclude=True)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=utc_now_iso)
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[EvidenceArtifact] = Field(default_factory=list)
    provider: Optional[str] = None

    def mark_started(self, timestamp: Optional[str] = None) -> "CallingExecutionContext":
        """Return a copy marked as started."""
        return self.model_copy(update={"started_at": timestamp or utc_now_iso()})

    def mark_ended(self, timestamp: Optional[str] = None) -> "CallingExecutionContext":
        """Return a copy marked as ended."""
        return self.model_copy(update={"ended_at": timestamp or utc_now_iso()})
