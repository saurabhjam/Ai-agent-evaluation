"""Provider abstraction for calling transcription."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from app.calling.audio_metadata import AudioMetadata
from app.calling.transcription import RawTranscript


class TranscriptionProvider(ABC):
    """Abstract STT provider interface."""

    provider_name: str

    @abstractmethod
    def transcribe(
        self,
        *,
        audio_uri: str,
        audio_metadata: Optional[AudioMetadata] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> RawTranscript:
        """Transcribe audio and return a raw provider-neutral transcript."""
        ...


class ManualTranscriptionProvider(TranscriptionProvider):
    """Provider for already-supplied manual/provider transcript data."""

    provider_name = "manual"

    def __init__(self, transcript: RawTranscript):
        self.transcript = transcript

    def transcribe(
        self,
        *,
        audio_uri: str,
        audio_metadata: Optional[AudioMetadata] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> RawTranscript:
        """Return the supplied transcript without external calls."""
        updates = {}
        if audio_metadata is not None and self.transcript.audio_metadata is None:
            updates["audio_metadata"] = audio_metadata
        if metadata:
            updates["metadata"] = {**self.transcript.metadata, **metadata}
        return self.transcript.model_copy(update=updates) if updates else self.transcript
