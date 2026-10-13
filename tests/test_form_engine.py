from app.interactive.component_models import Component, ComponentOption
from app.interactive.component_result import ComponentResult
from app.interactive.component_types import ComponentType
from app.interactive.field_types import FieldType
from app.interactive.form_context import FormContext
from app.interactive.form_engine import DefaultFormEngine
from app.interactive.form_registry import default_form_registry
from app.interactive.form_state import FormSubmissionState


def test_form_engine_groups_components_into_ordered_form_fields():
    context = FormContext(
        components=[
            Component(id="name", type=ComponentType.text_area, label="Name", required=True),
            Component(id="email", type=ComponentType.email_input, label="Email", required=True),
            Component(
                id="vehicle",
                type=ComponentType.dropdown,
                label="Vehicle Type",
                options=[ComponentOption(label="Car"), ComponentOption(label="Truck")],
            ),
            Component(id="submit", type=ComponentType.button, label="Submit"),
        ],
        variables={"name": "Ava", "email": "ava@example.com", "vehicle_type": "Car"},
        metadata={"title": "Lead Form"},
    )

    result = DefaultFormEngine().understand(context)

    assert result.success is True
    assert result.form_count == 1
    form = result.forms[0]
    assert form.title == "Lead Form"
    assert [field.type for field in form.fields] == [FieldType.textarea, FieldType.email, FieldType.dropdown]
    assert [field.current_value for field in form.fields] == ["Ava", "ava@example.com", "Car"]
    assert form.submission_state == FormSubmissionState.ready


def test_form_engine_returns_empty_result_when_no_fields_exist():
    result = DefaultFormEngine().understand(
        FormContext(components=[Component(type=ComponentType.text, label="Greeting", text="Hello")])
    )

    assert result.success is True
    assert result.forms == []


def test_form_context_can_be_created_from_component_result():
    component_result = ComponentResult(
        success=True,
        components=[Component(type=ComponentType.phone_input, label="Phone")],
    )

    context = FormContext.from_component_result(component_result, variables={"phone": "+15551234567"})

    assert context.components[0].label == "Phone"
    assert context.variables["phone"] == "+15551234567"


def test_form_registry_creates_default_engine():
    engine = default_form_registry().create("default")

    assert isinstance(engine, DefaultFormEngine)
