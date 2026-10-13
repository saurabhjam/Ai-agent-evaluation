"""Recording metadata ingestion for provider webhooks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.calling.models import CallRecording, CallSession
from app.calling.recording_registry import RecordingRegistry
from app.calling.recording_resolver import RecordingResolver


@dataclass
class RecordingIngestionService:
    """Resolves and stores recording metadata idempotently."""

    registry: RecordingRegistry = field(default_factory=RecordingRegistry)
    resolver: RecordingResolver = field(default_factory=RecordingResolver)

    def ingest(
        self,
        *,
        provider_name: str,
        session: CallSession,
        payload: dict[str, Any],
    ) -> CallRecording | None:
        """Ingest provider recording metadata without downloads."""
        recording = self.resolver.resolve(
            provider_name=provider_name,
            session=session,
            payload=payload,
        )
        if recording is None:
            return None
        return self.registry.upsert(recording).recording
