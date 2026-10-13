"""Provider-neutral transcript models for calling STT."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.calling.audio_metadata import AudioMetadata


class RawTranscriptSegment(BaseModel):
    """One raw transcript segment from any transcript source."""

    speaker: Optional[str] = None
    text: str = ""
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    confidence: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawTranscript(BaseModel):
    """Raw provider/manual/STT transcript before normalization."""

    source: str
    provider_name: Optional[str] = None
    segments: list[RawTranscriptSegment] = Field(default_factory=list)
    audio_metadata: Optional[AudioMetadata] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
