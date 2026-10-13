"""Provider resolver for calling provider infrastructure."""

from __future__ import annotations

from app.calling.config import CallingProviderConfig, default_mock_provider_config
from app.calling.exceptions import ProviderConfigurationError
from app.calling.provider_adapter import CallProviderAdapter
from app.calling.provider_factory import ProviderFactory
from app.calling.provider_loader import create_default_provider_registry
from app.calling.provider_registry import ProviderRegistry


class ProviderResolver:
    """Validates provider config and returns provider adapter instances."""

    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        factory: ProviderFactory | None = None,
    ):
        self.registry = registry or create_default_provider_registry()
        self.factory = factory or ProviderFactory(self.registry)

    def resolve(self, config: CallingProviderConfig | None = None) -> CallProviderAdapter:
        """Resolve a provider config into an adapter instance."""
        provider_config = config or default_mock_provider_config()
        self.validate(provider_config)
        return self.factory.create(provider_config)

    def validate(self, config: CallingProviderConfig) -> None:
        """Validate provider availability and generic config."""
        if not config.enabled:
            raise ProviderConfigurationError(
                f"Provider '{config.provider_name}' is disabled."
            )
        if not self.registry.exists(config.provider_name):
            # Use registry.get to preserve the canonical unknown-provider exception.
            self.registry.get(config.provider_name)
