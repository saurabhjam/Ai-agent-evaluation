from app.interactive.component_models import Component
from app.interactive.component_result import ComponentResult
from app.interactive.component_types import ComponentType
from app.interactive.planning_context import PlanningContext
from app.interactive.planning_models import PlannerType, PlanningStrategyDefinition


def test_planning_context_can_be_created_from_component_result():
    result = ComponentResult(
        success=True,
        components=[Component(type=ComponentType.email_input, label="Email")],
    )

    context = PlanningContext.from_component_result(
        result,
        variables={"email": "user@example.com"},
        current_step="contact",
    )

    assert context.components[0].label == "Email"
    assert context.variables["email"] == "user@example.com"
    assert context.current_step == "contact"


def test_planning_strategy_definition_requires_name():
    try:
        PlanningStrategyDefinition(name="", planner_type=PlannerType.default)
    except ValueError as exc:
        assert "name" in str(exc)
    else:
        raise AssertionError("Expected validation error")
