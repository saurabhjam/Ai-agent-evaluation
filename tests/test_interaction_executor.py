from app.interactive.interaction_context import InteractionContext
from app.interactive.interaction_executor import InteractionExecutor
from app.interactive.interaction_factory import InteractionFactory
from app.interactive.interaction_models import Interaction
from app.interactive.interaction_types import InteractionType


class FakeProviderAdapter:
    def __init__(self):
        self.calls = []

    def send_text(self, interaction, context):
        self.calls.append(("send_text", interaction.dispatch_value(), context.scenario_id))
        return {"reply": "ok"}

    def click_button(self, interaction, context):
        self.calls.append(("click_button", interaction.label, context.run_id))
        return "clicked"


def test_factory_creates_registered_interaction_from_payload():
    interaction = InteractionFactory().create({
        "id": "hello",
        "type": "TEXT",
        "label": "Message",
        "value": "Hello",
    })

    assert interaction.type == InteractionType.text
    assert interaction.dispatch_value() == "Hello"


def test_executor_dispatches_text_to_provider_adapter():
    adapter = FakeProviderAdapter()
    context = InteractionContext(adapter=adapter, scenario_id="scenario-1")

    result = InteractionExecutor().execute(
        Interaction(type=InteractionType.text, label="Message", value="Hello"),
        context,
    )

    assert result.success is True
    assert result.provider_response == {"reply": "ok"}
    assert adapter.calls == [("send_text", "Hello", "scenario-1")]


def test_executor_dispatches_button_to_provider_adapter():
    adapter = FakeProviderAdapter()
    context = InteractionContext(adapter=adapter, run_id="run-1")

    result = InteractionExecutor().execute(
        Interaction(type=InteractionType.button, label="Continue"),
        context,
    )

    assert result.success is True
    assert result.provider_response == "clicked"
    assert adapter.calls == [("click_button", "Continue", "run-1")]


def test_executor_returns_failure_for_unimplemented_provider_method():
    context = InteractionContext(adapter=object())

    result = InteractionExecutor().execute(
        Interaction(type=InteractionType.dropdown, label="Choose", value="A"),
        context,
    )

    assert result.success is False
    assert "select_option" in result.error
