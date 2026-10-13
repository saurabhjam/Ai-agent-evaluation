"""Configuration for OpenAI Whisper transcription."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, SecretStr, field_validator


class WhisperTranscriptionConfig(BaseModel):
    """Provider-neutral configuration for the Whisper STT implementation."""

    api_key: Optional[SecretStr] = None
    model: str = "whisper-1"
    language: Optional[str] = None
    temperature: float = 0.0
    prompt: Optional[str] = None
    timeout_seconds: Optional[float] = 60.0
    supported_formats: tuple[str, ...] = ("wav", "mp3", "m4a", "ogg")
    default_speaker_label: str = "speaker_0"

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Whisper model is required")
        return value.strip()

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Whisper temperature cannot be negative")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and value <= 0:
            raise ValueError("Whisper timeout must be greater than zero")
        return value

    @field_validator("supported_formats")
    @classmethod
    def validate_supported_formats(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.lower().lstrip(".") for item in value if item.strip())
        if not normalized:
            raise ValueError("At least one audio format must be supported")
        return normalized

    @field_validator("default_speaker_label")
    @classmethod
    def validate_default_speaker_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Default speaker label is required")
        return value.strip()
