from app.interactive.interaction_context import InteractionContext
from app.interactive.interaction_executor import InteractionExecutor
from app.interactive.interaction_models import Interaction
from app.interactive.interaction_plan import InteractionPlan, PlanStatus
from app.interactive.interaction_types import InteractionType
from app.interactive.workflow_context import WorkflowContext
from app.interactive.workflow_engine import DefaultWorkflowEngine
from app.interactive.workflow_registry import default_workflow_registry
from app.interactive.workflow_state import WorkflowStatus


class ProviderAdapter:
    def __init__(self):
        self.calls = []

    def send_text(self, interaction, context):
        self.calls.append(("send_text", interaction.value))
        return "ok"

    def click_button(self, interaction, context):
        self.calls.append(("click_button", interaction.label))
        return "clicked"


class FlakyExecutor:
    def __init__(self):
        self.calls = 0

    def execute(self, interaction, interaction_context):
        self.calls += 1
        if self.calls == 1:
            return type("Result", (), {"success": False, "error": "temporary", "message": "temporary"})()
        return type("Result", (), {"success": True, "error": None, "message": "ok"})()


def _context(adapter=None, executor=None, **kwargs):
    adapter = adapter or ProviderAdapter()
    return WorkflowContext(
        interaction_context=InteractionContext(adapter=adapter),
        interaction_executor=executor or InteractionExecutor(),
        **kwargs,
    )


def test_workflow_engine_executes_plan_in_order():
    adapter = ProviderAdapter()
    plan = InteractionPlan(
        ordered_interactions=[
            Interaction(type=InteractionType.text, label="Name", value="Ava"),
            Interaction(type=InteractionType.button, label="Submit"),
        ]
    )

    result = DefaultWorkflowEngine().run(plan, _context(adapter=adapter))

    assert result.success is True
    assert result.status == WorkflowStatus.completed
    assert [item.label for item in result.completed_interactions] == ["Name", "Submit"]
    assert adapter.calls == [("send_text", "Ava"), ("click_button", "Submit")]


def test_workflow_engine_tracks_failure():
    plan = InteractionPlan(
        ordered_interactions=[Interaction(type=InteractionType.dropdown, label="Vehicle", value="Car")]
    )

    result = DefaultWorkflowEngine().run(plan, _context(adapter=object()))

    assert result.success is False
    assert result.status == WorkflowStatus.failed
    assert result.failed_interactions[0].label == "Vehicle"


def test_workflow_engine_tracks_retries():
    executor = FlakyExecutor()
    plan = InteractionPlan(
        ordered_interactions=[Interaction(type=InteractionType.text, label="Message", value="Hello")]
    )

    result = DefaultWorkflowEngine().run(plan, _context(executor=executor, max_retries=1))

    assert result.success is True
    assert result.metadata["retry_count"] == 1
    assert executor.calls == 2


def test_workflow_engine_rejects_failed_plan():
    plan = InteractionPlan(status=PlanStatus.failed)

    result = DefaultWorkflowEngine().run(plan, _context())

    assert result.success is False
    assert result.status == WorkflowStatus.failed


def test_workflow_registry_creates_default_engine():
    engine = default_workflow_registry().create("default")

    assert isinstance(engine, DefaultWorkflowEngine)
