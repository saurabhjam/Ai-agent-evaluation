from app.interactive.models import (
    ActionType,
    InteractiveElement,
    InteractiveElementType,
    NormalizedAgentResponse,
    UserAction,
)


def test_interactive_element_strips_values_and_uses_label_fallback():
    element = InteractiveElement(
        type=InteractiveElementType.quick_reply,
        label="  Show all properties  ",
        value="  ",
    )

    assert element.label == "Show all properties"
    assert element.value is None
    assert element.action_value() == "Show all properties"


def test_normalized_response_reports_interactive_content():
    response = NormalizedAgentResponse(
        text="Choose one",
        interactive=[
            InteractiveElement(
                type=InteractiveElementType.button,
                label="Confirm",
                value="confirm",
            )
        ],
    )

    assert response.has_interactive_content is True


def test_user_action_uses_generic_action_type():
    action = UserAction(type=ActionType.click_option, target="Show entire portfolio")

    assert action.type == ActionType.click_option
    assert action.target == "Show entire portfolio"


def test_interactive_element_requires_label():
    try:
        InteractiveElement(type=InteractiveElementType.button, label="")
    except ValueError as exc:
        assert "label" in str(exc)
    else:
        raise AssertionError("Expected validation error")
