from app.interactive.conversation_state import ConversationStateBuilder
from app.interactive.models import (
    InteractiveElement,
    InteractiveElementType,
    NormalizedAgentResponse,
)


def test_conversation_state_builder_collects_available_actions():
    response = NormalizedAgentResponse(
        text="Choose one",
        interactive=[
            InteractiveElement(type=InteractiveElementType.quick_reply, label="Portfolio", value="portfolio"),
            InteractiveElement(type=InteractiveElementType.quick_reply, label="Single property"),
        ],
    )

    state = ConversationStateBuilder().build(
        scenario_id="maintenance",
        persona_goal="Report a maintenance issue",
        current_agent_response=response,
        known_facts={"issue": "water leak"},
        missing_facts=["unit number"],
    )

    assert state.scenario_id == "maintenance"
    assert state.current_goal == "Report a maintenance issue"
    assert state.available_actions == ["portfolio", "Single property"]
    assert state.known_facts["issue"] == "water leak"
    assert state.missing_facts == ["unit number"]
