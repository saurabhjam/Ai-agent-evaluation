import pytest

from app.interactive.interaction_models import Interaction
from app.interactive.interaction_plan import InteractionPlan, PlanStatus
from app.interactive.interaction_types import InteractionType


def test_interaction_plan_normalizes_status_and_confidence():
    plan = InteractionPlan(
        ordered_interactions=[Interaction(type=InteractionType.text, label="Name", value="Ava")],
        confidence=2,
        status="PLANNED",
    )

    assert plan.status == PlanStatus.planned
    assert plan.confidence == 1.0
    assert plan.is_actionable is True


def test_empty_plan_is_not_actionable():
    plan = InteractionPlan(status=PlanStatus.empty)

    assert plan.is_actionable is False


def test_interaction_plan_requires_id():
    with pytest.raises(ValueError, match="id"):
        InteractionPlan(id="")
