from app.interactive.action_validator import ActionValidator
from app.interactive.capability_registry import AdapterCapability, CapabilityRegistry
from app.interactive.models import ActionType, UserAction


def test_send_text_requires_text():
    result = ActionValidator().validate(
        UserAction(type=ActionType.send_text),
        adapter_name="rest",
    )

    assert result.valid is False
    assert "requires text" in result.reason


def test_supported_action_is_valid():
    result = ActionValidator().validate(
        UserAction(type=ActionType.click_option, target="Show all results"),
        adapter_name="rest",
    )

    assert result.valid is True
    assert result.normalized_action.type == ActionType.click_option


def test_unsupported_action_returns_text_fallback():
    registry = CapabilityRegistry()
    registry.register(
        AdapterCapability(
            adapter_name="text_only",
            supported_actions={ActionType.send_text},
        )
    )

    result = ActionValidator(registry).validate(
        UserAction(type=ActionType.click_button, target="Continue"),
        adapter_name="text_only",
    )

    assert result.valid is False
    assert result.normalized_action.type == ActionType.send_text
    assert result.normalized_action.text == "Continue"


def test_upload_action_requires_file():
    result = ActionValidator().validate(
        UserAction(type=ActionType.upload_file),
        adapter_name="rest",
    )

    assert result.valid is False
    assert "requires file" in result.reason
