from app.interactive.action_executor import ActionExecutor
from app.interactive.capability_registry import AdapterCapability, CapabilityRegistry
from app.interactive.action_validator import ActionValidator
from app.interactive.models import ActionType, UserAction
from app.interactive.planner import ActionProposal


class FakeAdapter:
    def __init__(self):
        self.messages = []
        self.actions = []
        self.uploads = []

    def send_message(self, message, agent_prompt=None, attachments=None):
        self.messages.append((message, agent_prompt, attachments))

    def execute_action(self, action):
        self.actions.append(action)

    def upload_file(self, file):
        self.uploads.append(file)


class NoUploadAdapter:
    def __init__(self):
        self.messages = []

    def send_message(self, message, agent_prompt=None, attachments=None):
        self.messages.append(message)


def _executor_with(actions):
    registry = CapabilityRegistry()
    registry.register(AdapterCapability(adapter_name="test", supported_actions=set(actions)))
    return ActionExecutor(ActionValidator(registry))


def test_send_text_executes_via_send_message():
    adapter = FakeAdapter()
    executor = _executor_with({ActionType.send_text})

    result = executor.execute(
        proposal=ActionProposal(UserAction(type=ActionType.send_text, text="Hello"), 0.9),
        adapter=adapter,
        adapter_name="test",
        agent_prompt="prompt",
    )

    assert result.success is True
    assert adapter.messages == [("Hello", "prompt", None)]


def test_click_option_falls_back_to_send_message_without_native_execute_action():
    adapter = NoUploadAdapter()
    executor = _executor_with({ActionType.send_text, ActionType.click_option})

    result = executor.execute(
        proposal=ActionProposal(
            UserAction(type=ActionType.click_option, target="Show portfolio", value="Show portfolio"),
            0.9,
        ),
        adapter=adapter,
        adapter_name="test",
    )

    assert result.success is True
    assert adapter.messages == ["Show portfolio"]


def test_click_button_without_declared_native_capability_uses_text_fallback():
    adapter = FakeAdapter()
    executor = _executor_with({ActionType.click_button})
    action = UserAction(type=ActionType.click_button, target="Continue")

    result = executor.execute(
        proposal=ActionProposal(action, 0.8),
        adapter=adapter,
        adapter_name="test",
    )

    assert result.success is True
    assert adapter.actions == []
    assert adapter.messages == [("Continue", None, None)]


def test_upload_uses_upload_file_when_supported():
    adapter = FakeAdapter()
    executor = _executor_with({ActionType.upload_file})

    result = executor.execute(
        proposal=ActionProposal(UserAction(type=ActionType.upload_file, file="damage.jpg"), 0.8),
        adapter=adapter,
        adapter_name="test",
    )

    assert result.success is True
    assert adapter.uploads == ["damage.jpg"]


def test_unsupported_action_uses_validator_send_text_fallback():
    adapter = NoUploadAdapter()
    executor = _executor_with({ActionType.send_text})

    result = executor.execute(
        proposal=ActionProposal(UserAction(type=ActionType.click_button, target="Continue"), 0.8),
        adapter=adapter,
        adapter_name="test",
    )

    assert result.success is True
    assert result.fallback_used is True
    assert result.executed_as == ActionType.send_text
    assert adapter.messages == ["Continue"]


def test_upload_without_adapter_support_reports_failure_when_no_text_fallback_exists():
    adapter = NoUploadAdapter()
    executor = _executor_with({ActionType.upload_file})

    result = executor.execute(
        proposal=ActionProposal(UserAction(type=ActionType.upload_file, file="damage.jpg"), 0.8),
        adapter=adapter,
        adapter_name="test",
    )

    assert result.success is False
    assert "file upload" in result.message
