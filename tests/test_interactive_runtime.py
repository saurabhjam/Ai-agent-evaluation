from app.interactive.interactive_runtime import (
    InteractiveRuntime,
    chatbot_execution_mode,
    interactive_runtime_enabled,
)
from app.interactive.runtime_context import RuntimeContext
from app.interactive.runtime_registry import default_runtime_registry
from app.interactive.workflow_state import WorkflowStatus


class ProviderAdapter:
    def __init__(self):
        self.calls = []

    def send_text(self, interaction, context):
        self.calls.append((interaction.label, interaction.value))
        return "ok"

    def click_button(self, interaction, context):
        self.calls.append((interaction.label, interaction.value))
        return "clicked"


def test_interactive_runtime_orchestrates_end_to_end():
    adapter = ProviderAdapter()
    context = RuntimeContext(
        adapter=adapter,
        provider="rest",
        provider_response={
            "components": [
                {"id": "email", "type": "EMAIL_INPUT", "label": "Email", "required": True},
                {"id": "submit", "type": "BUTTON", "label": "Submit"},
            ]
        },
        variables={"email": "ava@example.com"},
    )

    result = InteractiveRuntime().run(context)

    assert result.success is True
    assert result.workflow_status == WorkflowStatus.completed
    assert result.interaction_count == 2
    assert len(result.detected_components) == 2
    assert len(result.detected_forms) == 1
    assert adapter.calls == [("Email", "ava@example.com"), ("Submit", "Submit")]


def test_interactive_runtime_returns_failure_for_unhandled_payload():
    result = InteractiveRuntime().run(RuntimeContext(provider_response={"message": "hello"}))

    assert result.success is False
    assert result.workflow_status == WorkflowStatus.failed
    assert "parser" in result.error


def test_runtime_registry_creates_default_runtime():
    runtime = default_runtime_registry().create("default")

    assert isinstance(runtime, InteractiveRuntime)


def test_feature_flag_default_is_legacy(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "chatbot_execution_mode", "legacy")

    assert chatbot_execution_mode() == "legacy"
    assert interactive_runtime_enabled() is False


def test_feature_flag_allows_interactive(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "chatbot_execution_mode", "interactive")

    assert chatbot_execution_mode() == "interactive"
    assert interactive_runtime_enabled() is True


def test_unknown_feature_flag_falls_back_to_legacy(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "chatbot_execution_mode", "unknown")

    assert chatbot_execution_mode() == "legacy"
