from app.interactive.capability_registry import (
    AdapterCapability,
    CapabilityRegistry,
    default_capability_registry,
)
from app.interactive.models import ActionType


def test_unknown_adapter_defaults_to_text_only():
    registry = CapabilityRegistry()

    assert registry.supports("unknown", ActionType.send_text) is True
    assert registry.supports("unknown", ActionType.upload_file) is False


def test_register_adapter_capability():
    registry = CapabilityRegistry()
    registry.register(
        AdapterCapability(
            adapter_name="custom",
            supported_actions={ActionType.send_text, ActionType.upload_file},
        )
    )

    assert registry.supports("custom", ActionType.upload_file) is True


def test_default_registry_declares_existing_adapter_names_without_importing_them():
    registry = default_capability_registry()

    assert registry.supports("rest", ActionType.send_text) is True
    assert registry.supports("rest", ActionType.click_option) is True
    assert registry.supports("livekit", ActionType.dtmf) is True
