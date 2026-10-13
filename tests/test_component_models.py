import pytest

from app.interactive.component_models import Component, ComponentOption
from app.interactive.component_result import ComponentResult
from app.interactive.component_types import ComponentType


def test_component_model_normalizes_values_and_options():
    component = Component(
        id=" dropdown ",
        type="DROPDOWN",
        label=" Choose one ",
        selector="  ",
        options=[{"label": " A ", "value": "a"}],
    )

    assert component.id == "dropdown"
    assert component.type == ComponentType.dropdown
    assert component.label == "Choose one"
    assert component.selector is None
    assert component.has_options is True
    assert isinstance(component.options[0], ComponentOption)
    assert component.options[0].label == "A"


def test_component_requires_id_and_label():
    with pytest.raises(ValueError, match="id"):
        Component(id="", type=ComponentType.button, label="Continue")

    with pytest.raises(ValueError, match="label"):
        Component(type=ComponentType.button, label="")


def test_component_option_uses_label_fallback_value():
    option = ComponentOption(label="Confirm")

    assert option.option_value() == "Confirm"


def test_component_result_counts_components():
    result = ComponentResult(
        success=True,
        components=[Component(type=ComponentType.text, label="Hello")],
        provider="generic",
    )

    assert result.component_count == 1
    assert result.provider == "generic"
