"""Lazy provider registry bootstrap for the calling subsystem."""

from __future__ import annotations

from app.calling.provider_registry import ProviderRegistry
from app.calling.providers.mock import MockCallProvider


def create_default_provider_registry() -> ProviderRegistry:
    """
    Create the default provider registry.

    Providers are registered only when their concrete implementation exists.
    Missing optional SDKs should fail during provider execution, not by silently
    changing the configured provider.
    """
    registry = ProviderRegistry()
    registry.register("mock", MockCallProvider)

    try:
        from app.calling.providers.twilio import TwilioProvider
        registry.register("twilio", TwilioProvider)
    except ImportError:
        pass

    try:
        from app.calling.providers.vapi import VapiProvider
        registry.register("vapi", VapiProvider)
    except ImportError:
        pass

    return registry
