from __future__ import annotations

import pytest

from app.calling.config import CallingProviderConfig
from app.calling.exceptions import ProviderConfigurationError, ProviderInitializationError
from app.calling.provider_factory import ProviderFactory
from app.calling.provider_registry import ProviderRegistry
from app.calling.providers.mock import MockCallProvider


def test_provider_factory_creates_mock_provider():
    registry = ProviderRegistry()
    registry.register("mock", MockCallProvider)
    factory = ProviderFactory(registry)

    provider = factory.create(CallingProviderConfig(provider_name="mock"))

    assert isinstance(provider, MockCallProvider)


def test_provider_factory_rejects_disabled_provider():
    registry = ProviderRegistry()
    registry.register("mock", MockCallProvider)
    factory = ProviderFactory(registry)

    with pytest.raises(ProviderConfigurationError):
        factory.create(CallingProviderConfig(provider_name="mock", enabled=False))


def test_provider_factory_wraps_initialization_errors():
    class BrokenProvider(MockCallProvider):
        def __init__(self):
            raise RuntimeError("boom")

    registry = ProviderRegistry()
    registry.register("broken", BrokenProvider)
    factory = ProviderFactory(registry)

    with pytest.raises(ProviderInitializationError):
        factory.create(CallingProviderConfig(provider_name="broken"))
