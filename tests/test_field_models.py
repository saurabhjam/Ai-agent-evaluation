import pytest

from app.interactive.component_models import ComponentOption
from app.interactive.field_models import Field, FieldValidationRule
from app.interactive.field_types import FieldType
from app.interactive.form_state import FieldValidationType


def test_field_model_normalizes_type_options_and_required_rule():
    field = Field(
        id=" email ",
        type="EMAIL",
        label=" Email ",
        required=True,
        current_value="user@example.com",
        options=[{"label": "Primary"}],
    )

    assert field.id == "email"
    assert field.type == FieldType.email
    assert field.label == "Email"
    assert field.is_completed is True
    assert isinstance(field.options[0], ComponentOption)
    assert any(rule.type == FieldValidationType.required for rule in field.validation_rules)


def test_field_requires_id_and_label():
    with pytest.raises(ValueError, match="id"):
        Field(id="", type=FieldType.text, label="Name")

    with pytest.raises(ValueError, match="label"):
        Field(type=FieldType.text, label="")


def test_validation_rule_normalizes_type():
    rule = FieldValidationRule(type="REGEX", value=r"^[a-z]+$")

    assert rule.type == FieldValidationType.regex
