from __future__ import annotations

import pytest

from app.calling.config import CallingProviderConfig, default_mock_provider_config
from app.calling.exceptions import ProviderConfigurationError, UnknownProviderError
from app.calling.provider_loader import create_default_provider_registry
from app.calling.provider_resolver import ProviderResolver
from app.calling.provider_registry import ProviderRegistry
from app.calling.providers.mock import MockCallProvider
from app.calling.providers.vapi import VapiProvider
from app.calling.runner import CallSessionRunner


def test_default_provider_registry_registers_runtime_providers():
    registry = create_default_provider_registry()

    assert "mock" in registry.list()
    assert "vapi" in registry.list()
    assert registry.get("mock") is MockCallProvider
    assert registry.get("vapi") is VapiProvider


def test_provider_resolver_resolves_default_mock_provider():
    resolver = ProviderResolver()

    provider = resolver.resolve()

    assert isinstance(provider, MockCallProvider)


def test_provider_resolver_resolves_configured_mock_provider():
    registry = ProviderRegistry()
    registry.register("mock", MockCallProvider)
    resolver = ProviderResolver(registry=registry)

    provider = resolver.resolve(CallingProviderConfig(provider_name=" MOCK "))

    assert isinstance(provider, MockCallProvider)


def test_provider_resolver_unknown_provider_fails():
    resolver = ProviderResolver(registry=ProviderRegistry())

    with pytest.raises(UnknownProviderError):
        resolver.resolve(CallingProviderConfig(provider_name="missing"))


def test_provider_resolver_disabled_provider_fails():
    resolver = ProviderResolver()

    with pytest.raises(ProviderConfigurationError):
        resolver.resolve(CallingProviderConfig(provider_name="mock", enabled=False))


def test_default_mock_provider_config_has_generic_fields():
    config = default_mock_provider_config(metadata={"phase": 3})

    assert config.provider_name == "mock"
    assert config.enabled is True
    assert config.settings == {}
    assert config.credentials == {}
    assert config.timeouts == {}
    assert config.metadata == {"phase": 3}


def test_runner_uses_resolver_when_adapter_not_injected():
    runner = CallSessionRunner(
        provider_resolver=ProviderResolver(),
        provider_config=CallingProviderConfig(provider_name="mock"),
    )

    result = runner.run_mock_call(scenario_id="resolver-call")

    assert result.execution_result.success is True
    assert result.execution_result.session.provider_name == "mock"
    assert result.normalized_conversation.metadata["scenario_id"] == "resolver-call"
