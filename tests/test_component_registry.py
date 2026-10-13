import pytest

from app.interactive.component_registry import (
    ComponentDefinition,
    ComponentRegistry,
    default_component_registry,
)
from app.interactive.component_types import ComponentType, SUPPORTED_COMPONENT_TYPES


def test_default_component_registry_registers_all_supported_types():
    registry = default_component_registry()

    assert set(registry.list_types()) == set(SUPPORTED_COMPONENT_TYPES)
    assert registry.has(ComponentType.button) is True
    assert registry.has("HTML") is True


def test_component_registry_prevents_duplicate_registration():
    registry = ComponentRegistry()
    registry.register(ComponentDefinition(type=ComponentType.text))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(ComponentDefinition(type=ComponentType.text))


def test_component_registry_supports_overwrite():
    registry = ComponentRegistry()
    registry.register(ComponentDefinition(type=ComponentType.unknown, description="old"))
    registry.register(ComponentDefinition(type=ComponentType.unknown, description="new"), overwrite=True)

    assert registry.get(ComponentType.unknown).description == "new"
    assert registry.has("NOT_A_TYPE") is False
