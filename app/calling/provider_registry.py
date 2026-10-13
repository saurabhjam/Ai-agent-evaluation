"""Plugin-style registry for calling providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Type

from app.calling.exceptions import DuplicateProviderError, ProviderRegistrationError, UnknownProviderError
from app.calling.provider_adapter import CallProviderAdapter


ProviderClass = Type[CallProviderAdapter]


@dataclass
class ProviderRegistry:
    """Stores provider names mapped to provider adapter classes."""

    _providers: dict[str, ProviderClass] = field(default_factory=dict)

    def register(self, name: str, provider_cls: ProviderClass) -> None:
        """Register a provider class by name."""
        key = self._normalize_name(name)
        if key in self._providers:
            raise DuplicateProviderError(f"Provider '{key}' is already registered.")
        if not isinstance(provider_cls, type) or not issubclass(provider_cls, CallProviderAdapter):
            raise ProviderRegistrationError(
                f"Provider '{key}' must be a CallProviderAdapter subclass."
            )
        self._providers[key] = provider_cls

    def unregister(self, name: str) -> None:
        """Remove a provider registration."""
        key = self._normalize_name(name)
        if key not in self._providers:
            raise UnknownProviderError(f"Provider '{key}' is not registered.")
        del self._providers[key]

    def get(self, name: str) -> ProviderClass:
        """Return a registered provider class."""
        key = self._normalize_name(name)
        try:
            return self._providers[key]
        except KeyError as exc:
            raise UnknownProviderError(f"Provider '{key}' is not registered.") from exc

    def list(self) -> list[str]:
        """Return registered provider names."""
        return sorted(self._providers)

    def exists(self, name: str) -> bool:
        """Return whether a provider name is registered."""
        return self._normalize_name(name) in self._providers

    @staticmethod
    def _normalize_name(name: str) -> str:
        key = name.strip().lower()
        if not key:
            raise ProviderRegistrationError("Provider name must not be empty.")
        return key
