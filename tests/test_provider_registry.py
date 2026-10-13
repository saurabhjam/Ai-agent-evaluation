from __future__ import annotations

import pytest

from app.calling.exceptions import DuplicateProviderError, ProviderRegistrationError, UnknownProviderError
from app.calling.provider_registry import ProviderRegistry
from app.calling.providers.mock import MockCallProvider


def test_provider_registry_register_get_exists_list():
    registry = ProviderRegistry()

    registry.register("mock", MockCallProvider)

    assert registry.exists("mock")
    assert registry.exists(" MOCK ")
    assert registry.get("mock") is MockCallProvider
    assert registry.list() == ["mock"]


def test_provider_registry_duplicate_registration_fails():
    registry = ProviderRegistry()
    registry.register("mock", MockCallProvider)

    with pytest.raises(DuplicateProviderError):
        registry.register("mock", MockCallProvider)


def test_provider_registry_unknown_provider_fails():
    registry = ProviderRegistry()

    with pytest.raises(UnknownProviderError):
        registry.get("missing")


def test_provider_registry_unregister():
    registry = ProviderRegistry()
    registry.register("mock", MockCallProvider)

    registry.unregister("mock")

    assert not registry.exists("mock")


def test_provider_registry_rejects_non_adapter_class():
    registry = ProviderRegistry()

    with pytest.raises(ProviderRegistrationError):
        registry.register("bad", object)
