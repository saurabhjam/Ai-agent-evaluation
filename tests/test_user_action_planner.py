import json

from app.interactive.capability_registry import AdapterCapability, CapabilityRegistry
from app.interactive.conversation_state import ConversationStateBuilder
from app.interactive.models import (
    ActionType,
    InteractiveElement,
    InteractiveElementType,
    NormalizedAgentResponse,
)
from app.interactive.planner import LLMActionPlanner, RuleBasedFallbackPlanner, UserActionEngine


class FakeLLMClient:
    def __init__(self, payload):
        self.payload = payload

    def complete_action(self, prompt: str) -> str:
        assert "available_actions" in prompt
        return json.dumps(self.payload)


def _state(response, goal="Report a maintenance issue across my entire portfolio"):
    return ConversationStateBuilder().build(
        scenario_id="scenario",
        persona_goal=goal,
        current_agent_response=response,
    )


def test_rule_based_planner_selects_best_matching_quick_reply():
    response = NormalizedAgentResponse(
        text="Choose one",
        interactive=[
            InteractiveElement(type=InteractiveElementType.quick_reply, label="Charlie Parker"),
            InteractiveElement(type=InteractiveElementType.quick_reply, label="Harris Park"),
            InteractiveElement(type=InteractiveElementType.quick_reply, label="Show results across my entire portfolio"),
        ],
    )

    proposal = RuleBasedFallbackPlanner().plan(state=_state(response), adapter_name="rest")

    assert proposal.action.type == ActionType.click_option
    assert proposal.action.target == "Show results across my entire portfolio"
    assert 0.0 <= proposal.confidence <= 1.0


def test_rule_based_planner_uses_send_text_without_interactive_content():
    response = NormalizedAgentResponse(text="What is your maintenance issue?")

    proposal = RuleBasedFallbackPlanner().plan(
        state=_state(response, goal="Report a water leak maintenance issue"),
        adapter_name="rest",
    )

    assert proposal.action.type == ActionType.send_text
    assert proposal.action.text == "I need to report a maintenance issue."


def test_llm_action_planner_parses_structured_json():
    planner = LLMActionPlanner(
        FakeLLMClient(
            {
                "action": {"type": "CLICK_OPTION", "target": "Portfolio", "value": "portfolio"},
                "confidence": 0.96,
                "reason": "Best option.",
            }
        )
    )

    proposal = planner.plan(state=_state(NormalizedAgentResponse()), adapter_name="rest")

    assert proposal.action.type == ActionType.click_option
    assert proposal.action.value == "portfolio"
    assert proposal.confidence == 0.96


def test_user_action_engine_falls_back_when_llm_fails():
    engine = UserActionEngine(llm_planner=LLMActionPlanner(FakeLLMClient("not-json")))
    response = NormalizedAgentResponse(
        text="Choose one",
        interactive=[InteractiveElement(type=InteractiveElementType.quick_reply, label="Continue")],
    )

    proposal = engine.propose_action(state=_state(response), adapter_name="rest")

    assert proposal.action.type == ActionType.click_option
    assert proposal.action.target == "Continue"
    assert proposal.metadata["planner"] == "rule_based"


def test_user_action_engine_uses_validator_fallback_for_unsupported_action():
    registry = CapabilityRegistry()
    registry.register(AdapterCapability(adapter_name="text_only", supported_actions={ActionType.send_text}))
    response = NormalizedAgentResponse(
        text="Upload damage photo.",
        interactive=[
            InteractiveElement(
                type=InteractiveElementType.upload_request,
                label="Upload file",
                value="damage_photo.jpg",
                metadata={"file": "damage_photo.jpg"},
            )
        ],
    )

    proposal = UserActionEngine(capability_registry=registry).propose_action(
        state=_state(response),
        adapter_name="text_only",
    )

    assert proposal.action.type == ActionType.send_text
    assert proposal.action.text == "damage_photo.jpg"
    assert proposal.metadata["planner"] == "validator_fallback"
