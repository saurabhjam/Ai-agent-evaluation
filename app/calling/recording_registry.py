"""In-memory recording registry for calling provider webhook ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.calling.models import CallRecording
from app.calling.webhook_models import RecordingRegistryEntry


@dataclass
class RecordingRegistry:
    """Stores recording metadata only; no download or cloud storage."""

    _entries: dict[str, RecordingRegistryEntry] = field(default_factory=dict)

    def upsert(self, recording: CallRecording) -> RecordingRegistryEntry:
        """Insert or update a recording entry idempotently."""
        key = self._key(recording)
        existing = self._entries.get(key)
        if existing:
            merged = recording.model_copy(
                update={
                    "metadata": {**existing.recording.metadata, **recording.metadata},
                    "remote_url": recording.remote_url or existing.recording.remote_url,
                    "duration_seconds": recording.duration_seconds or existing.recording.duration_seconds,
                }
            )
            entry = existing.model_copy(update={"recording": merged})
        else:
            entry = RecordingRegistryEntry(
                recording=recording,
                provider=recording.provider,
                provider_name=recording.provider_name or "unknown",
                provider_recording_id=recording.provider_recording_id or recording.recording_id,
                provider_metadata=recording.metadata,
            )
        self._entries[key] = entry
        return entry

    def get(self, provider_recording_id: str) -> RecordingRegistryEntry:
        """Return a recording registry entry by provider recording id."""
        return self._entries[provider_recording_id]

    def exists(self, provider_recording_id: str) -> bool:
        """Return whether a provider recording id is registered."""
        return provider_recording_id in self._entries

    def list(self, *, session_id: Optional[str] = None) -> list[RecordingRegistryEntry]:
        """List entries, optionally scoped to a session."""
        entries = list(self._entries.values())
        if session_id is not None:
            entries = [entry for entry in entries if entry.recording.session_id == session_id]
        return entries

    @staticmethod
    def _key(recording: CallRecording) -> str:
        return recording.provider_recording_id or recording.recording_id or recording.artifact_id
