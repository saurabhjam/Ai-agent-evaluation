"""Models and errors for Whisper transcription."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class WhisperResponseFormat(str, Enum):
    """OpenAI transcription response formats used by the provider."""

    verbose_json = "verbose_json"


class WhisperSegment(BaseModel):
    """Provider-local representation of a Whisper segment."""

    text: str = ""
    start: Optional[float] = None
    end: Optional[float] = None
    confidence: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WhisperTranscriptionError(RuntimeError):
    """Base error for Whisper transcription failures."""


class WhisperAPIError(WhisperTranscriptionError):
    """Raised when the upstream Whisper API fails."""


class WhisperTimeoutError(WhisperTranscriptionError):
    """Raised when the upstream Whisper API times out."""


class WhisperEmptyTranscriptError(WhisperTranscriptionError):
    """Raised when Whisper returns no transcript text."""


class WhisperInvalidAudioError(WhisperTranscriptionError):
    """Raised when the requested audio input cannot be transcribed."""
