"""Provider factory for calling provider adapters."""

from __future__ import annotations

from app.calling.config import CallingProviderConfig
from app.calling.exceptions import ProviderConfigurationError, ProviderInitializationError
from app.calling.provider_adapter import CallProviderAdapter
from app.calling.provider_registry import ProviderRegistry


class ProviderFactory:
    """Creates provider instances from provider config and registry entries."""

    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    def create(self, config: CallingProviderConfig) -> CallProviderAdapter:
        """Instantiate the configured provider adapter."""
        if not config.enabled:
            raise ProviderConfigurationError(
                f"Provider '{config.provider_name}' is disabled."
            )
        provider_cls = self.registry.get(config.provider_name)
        try:
            try:
                return provider_cls(config=config)
            except TypeError:
                return provider_cls()
        except Exception as exc:
            raise ProviderInitializationError(
                f"Failed to initialize provider '{config.provider_name}': {exc}"
            ) from exc
