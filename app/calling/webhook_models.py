"""Provider-neutral webhook ingestion models."""

from __future__ import annotations

from typing import Any, Optional
import uuid

from pydantic import BaseModel, Field

from app.calling.conversation_evidence import ConversationEvidence
from app.calling.models import CallEvent, CallProvider, CallRecording, CallSession, utc_now_iso


class WebhookPayload(BaseModel):
    """Generic provider webhook payload wrapper."""

    provider_name: str
    payload: dict[str, Any]
    received_at: str = Field(default_factory=utc_now_iso)
    event_id: Optional[str] = None


class WebhookIngestionResult(BaseModel):
    """Result of processing one provider webhook."""

    ingestion_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    provider_name: str
    session: CallSession
    event: Optional[CallEvent] = None
    recording: Optional[CallRecording] = None
    conversation_evidence: Optional[ConversationEvidence] = None
    duplicate: bool = False
    ignored: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecordingRegistryEntry(BaseModel):
    """Metadata stored for a provider recording."""

    recording: CallRecording
    provider: CallProvider
    provider_name: str
    provider_recording_id: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
