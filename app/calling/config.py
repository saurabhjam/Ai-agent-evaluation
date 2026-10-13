"""Generic provider configuration for AI Calling Agent Evaluation."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class CallingProviderConfig(BaseModel):
    """
    Provider-neutral configuration consumed by the provider infrastructure.

    Provider-specific fields should remain inside concrete provider
    implementations and be passed through settings or credentials.
    """

    provider_name: str = Field(default="mock", min_length=1)
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] = Field(default_factory=dict)
    timeouts: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider_name")
    @classmethod
    def normalize_provider_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("provider_name must not be empty")
        return normalized


def default_mock_provider_config(metadata: Optional[dict[str, Any]] = None) -> CallingProviderConfig:
    """Return the default in-memory mock provider config."""
    return CallingProviderConfig(provider_name="mock", metadata=metadata or {})
