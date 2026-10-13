from app.interactive.component_models import Component, ComponentOption
from app.interactive.component_types import ComponentType
from app.interactive.decision_planner import DefaultDecisionPlanner
from app.interactive.interaction_plan import PlanStatus
from app.interactive.interaction_types import InteractionType
from app.interactive.planning_context import PlanningContext
from app.interactive.planning_registry import default_planning_registry


def test_default_planner_maps_inputs_and_submit_button_to_ordered_plan():
    context = PlanningContext(
        components=[
            Component(type=ComponentType.text_area, label="Name"),
            Component(type=ComponentType.email_input, label="Email"),
            Component(type=ComponentType.phone_input, label="Phone"),
            Component(type=ComponentType.button, label="Submit"),
        ],
        variables={
            "name": "Ava",
            "email": "ava@example.com",
            "phone": "+15551234567",
        },
    )

    plan = DefaultDecisionPlanner().plan(context)

    assert plan.status == PlanStatus.planned
    assert [item.type for item in plan.ordered_interactions] == [
        InteractionType.text,
        InteractionType.email_input,
        InteractionType.phone_input,
        InteractionType.button,
    ]
    assert [item.value for item in plan.ordered_interactions] == [
        "Ava",
        "ava@example.com",
        "+15551234567",
        "Submit",
    ]


def test_default_planner_maps_dropdown_from_scenario_variable():
    context = PlanningContext(
        components=[
            Component(
                type=ComponentType.dropdown,
                label="Vehicle Type",
                options=[
                    ComponentOption(label="Car", value="Car"),
                    ComponentOption(label="Truck", value="Truck"),
                ],
            )
        ],
        variables={"vehicle_type": "Car"},
    )

    plan = DefaultDecisionPlanner().plan(context)

    assert plan.ordered_interactions[0].type == InteractionType.dropdown
    assert plan.ordered_interactions[0].value == "Car"


def test_default_planner_maps_upload_as_plan_only_upload_file():
    context = PlanningContext(
        components=[Component(type=ComponentType.upload, label="Upload Damage Photo")],
        variables={"upload_damage_photo": "damage.jpg"},
    )

    plan = DefaultDecisionPlanner().plan(context)

    assert plan.ordered_interactions[0].type == InteractionType.upload_file
    assert plan.ordered_interactions[0].value == "damage.jpg"


def test_default_planner_ignores_non_actionable_display_components():
    context = PlanningContext(
        components=[Component(type=ComponentType.text, label="Greeting", text="Hello")]
    )

    plan = DefaultDecisionPlanner().plan(context)

    assert plan.status == PlanStatus.empty
    assert plan.is_actionable is False


def test_planning_registry_creates_default_planner():
    planner = default_planning_registry().create("default")

    assert isinstance(planner, DefaultDecisionPlanner)
