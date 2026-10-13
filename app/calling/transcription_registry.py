"""Registry for transcription providers."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.calling.transcription_provider import TranscriptionProvider


class UnknownTranscriptionProviderError(ValueError):
    """Raised when a transcription provider is not registered."""


class DuplicateTranscriptionProviderError(ValueError):
    """Raised when registering a duplicate transcription provider."""


@dataclass
class TranscriptionProviderRegistry:
    """Stores transcription providers by name."""

    _providers: dict[str, TranscriptionProvider] = field(default_factory=dict)

    def register(self, provider: TranscriptionProvider) -> None:
        """Register a transcription provider instance."""
        key = provider.provider_name.strip().lower()
        if not key:
            raise ValueError("Transcription provider name must not be empty.")
        if key in self._providers:
            raise DuplicateTranscriptionProviderError(f"Provider '{key}' already registered.")
        self._providers[key] = provider

    def get(self, provider_name: str) -> TranscriptionProvider:
        """Return a registered provider."""
        key = provider_name.strip().lower()
        try:
            return self._providers[key]
        except KeyError as exc:
            raise UnknownTranscriptionProviderError(f"Provider '{key}' is not registered.") from exc

    def list(self) -> list[str]:
        """Return registered provider names."""
        return sorted(self._providers)
