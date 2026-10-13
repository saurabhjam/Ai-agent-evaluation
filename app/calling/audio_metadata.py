"""Audio metadata models for calling transcription."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class AudioMetadata(BaseModel):
    """Provider-neutral metadata for a call recording/audio artifact."""

    duration_seconds: Optional[float] = None
    codec: Optional[str] = None
    sample_rate_hz: Optional[int] = None
    channels: Optional[int] = None
    bitrate_bps: Optional[int] = None
    file_size_bytes: Optional[int] = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
