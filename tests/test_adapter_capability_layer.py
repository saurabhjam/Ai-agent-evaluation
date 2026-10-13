from app.interactive.action_executor import ActionExecutor
from app.interactive.adapter_action import AdapterCapabilityResolver
from app.interactive.adapter_capabilities import (
    AdapterCapabilities,
    browser_placeholder_capabilities,
    rest_adapter_capabilities,
    voice_placeholder_capabilities,
)
from app.interactive.capability_registry import AdapterCapability, CapabilityRegistry
from app.interactive.action_validator import ActionValidator
from app.interactive.models import ActionType, UserAction
from app.interactive.planner import ActionProposal


class NativeAdapter:
    def __init__(self):
        self.actions = []
        self.messages = []

    def get_capabilities(self):
        return AdapterCapabilities(
            supports_send_text=True,
            supports_click_option=True,
            supports_upload=True,
        )

    def execute_action(self, action):
        self.actions.append(action)

    def send_message(self, message, agent_prompt=None, attachments=None):
        self.messages.append(message)


class SendOnlyAdapter:
    def __init__(self):
        self.messages = []

    def send_message(self, message, agent_prompt=None, attachments=None):
        self.messages.append(message)


def _executor_with(actions):
    registry = CapabilityRegistry()
    registry.register(AdapterCapability(adapter_name="test", supported_actions=set(actions)))
    return ActionExecutor(ActionValidator(registry))


def test_rest_capabilities_are_text_and_option_fallback_only():
    caps = rest_adapter_capabilities()

    assert caps.supports_action(ActionType.send_text)
    assert caps.supports_action(ActionType.click_option)
    assert caps.supports_action(ActionType.click_button)
    assert not caps.supports_action(ActionType.upload_file)


def test_browser_and_voice_placeholder_capabilities_are_declared():
    browser_caps = browser_placeholder_capabilities()
    voice_caps = voice_placeholder_capabilities()

    assert browser_caps.supports_dom_click is True
    assert browser_caps.supports_action(ActionType.select_dropdown)
    assert voice_caps.supports_dtmf is True
    assert voice_caps.supports_transfer is True


def test_resolver_uses_optional_get_capabilities():
    adapter = NativeAdapter()

    caps = AdapterCapabilityResolver().capabilities_for(adapter, adapter_name="custom")

    assert caps.supports_action(ActionType.click_option)
    assert caps.supports_action(ActionType.upload_file)


def test_native_execution_uses_execute_action_when_supported():
    adapter = NativeAdapter()
    executor = _executor_with({ActionType.click_option})
    action = UserAction(type=ActionType.click_option, target="Portfolio", value="portfolio")

    result = executor.execute(
        proposal=ActionProposal(action, 0.9),
        adapter=adapter,
        adapter_name="test",
    )

    assert result.success is True
    assert adapter.actions == [action]
    assert adapter.messages == []


def test_missing_execute_action_falls_back_to_send_message():
    adapter = SendOnlyAdapter()
    executor = _executor_with({ActionType.click_option})

    result = executor.execute(
        proposal=ActionProposal(
            UserAction(type=ActionType.click_option, target="Portfolio", value="portfolio"),
            0.9,
        ),
        adapter=adapter,
        adapter_name="test",
    )

    assert result.success is True
    assert adapter.messages == ["portfolio"]


def test_unsupported_action_still_uses_validator_fallback():
    adapter = SendOnlyAdapter()
    executor = _executor_with({ActionType.send_text})

    result = executor.execute(
        proposal=ActionProposal(UserAction(type=ActionType.click_button, target="Continue"), 0.9),
        adapter=adapter,
        adapter_name="test",
    )

    assert result.success is True
    assert result.fallback_used is True
    assert result.executed_as == ActionType.send_text
    assert adapter.messages == ["Continue"]
