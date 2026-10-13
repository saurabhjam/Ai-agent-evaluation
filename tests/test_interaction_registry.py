import pytest

from app.interactive.interaction_registry import (
    InteractionDefinition,
    InteractionRegistry,
    default_interaction_registry,
)
from app.interactive.interaction_types import InteractionType, SUPPORTED_INTERACTION_TYPES


def test_default_registry_registers_all_supported_types():
    registry = default_interaction_registry()

    assert set(registry.list_types()) == set(SUPPORTED_INTERACTION_TYPES)
    assert registry.get(InteractionType.text).handler_name == "send_text"
    assert registry.get(InteractionType.button).handler_name == "click_button"
    assert registry.get(InteractionType.dropdown).handler_name == "select_option"


def test_registry_prevents_duplicate_registration_by_default():
    registry = InteractionRegistry()
    registry.register(InteractionDefinition(type=InteractionType.text, handler_name="send_text"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(InteractionDefinition(type=InteractionType.text, handler_name="send_text_again"))


def test_registry_supports_overwrite_and_has():
    registry = InteractionRegistry()
    registry.register(InteractionDefinition(type=InteractionType.custom_action, handler_name="old"))
    registry.register(
        InteractionDefinition(type=InteractionType.custom_action, handler_name="new"),
        overwrite=True,
    )

    assert registry.has("CUSTOM_ACTION") is True
    assert registry.has("NOT_A_TYPE") is False
    assert registry.get(InteractionType.custom_action).handler_name == "new"
