from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from app.models.conversation import ConversationMessage
from app.schemas import Persona, TestScenario
from app.simulator import decide_next_user_action, generate_next_user_turn


def _groq_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _prompt(mock_groq) -> str:
    request = mock_groq.return_value.chat.completions.create.call_args.kwargs
    return "\n".join(message["content"] for message in request["messages"])


def test_scenario_model_preserves_context_and_behavior():
    scenario = TestScenario.model_validate(
        yaml.safe_load(
            """
scenario_id: generic-grounding
agent:
  channel: chatbot
persona:
  name: Alex
  role: requester
  goal: Submit a request and learn the next steps.
  tone: concise
context:
  identifier: Do not invent an identifier.
behavior:
  - If asked for the identifier, say it is unavailable.
  - Do not invent missing facts.
"""
        )
    )

    assert scenario.context == {"identifier": "Do not invent an identifier."}
    assert scenario.behavior == [
        "If asked for the identifier, say it is unavailable.",
        "Do not invent missing facts.",
    ]


@pytest.mark.parametrize(
    ("goal", "context", "behavior", "agent_message", "reply"),
    [
        (
            "Submit a service request and learn the next steps.",
            {"identifier": "Unknown; do not invent an identifier."},
            ["If asked for the identifier, explain that it is unavailable."],
            "What is the request identifier?",
            "I do not have the identifier available right now.",
        ),
        (
            "Ask for help with an account access problem.",
            {},
            ["Do not provide an account number."],
            "Please provide the account number.",
            "I cannot provide an account number.",
        ),
    ],
)
def test_missing_or_prohibited_information_is_not_invented(
    goal, context, behavior, agent_message, reply
):
    persona = Persona(name="Alex", goal=goal, tone="concise")
    transcript = [ConversationMessage(role="agent", content=agent_message, turn_index=0)]

    with patch("app.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = _groq_response(reply)
        result = generate_next_user_turn(
            persona,
            transcript,
            scenario_context=context,
            behavior_constraints=behavior,
        )

    assert result["message"] == reply
    prompt = _prompt(groq)
    assert json.dumps(context, ensure_ascii=True, sort_keys=True) in prompt
    assert json.dumps(behavior, ensure_ascii=True) in prompt
    assert "must not replace or contradict" in prompt
    assert "Do not fabricate" in prompt


def test_initial_message_receives_authoritative_context_and_constraints():
    persona = Persona(
        name="Alex",
        goal="Report a facilities problem and understand the process.",
        tone="professional",
    )
    context = {
        "issue": "Water is leaking from the ceiling.",
        "location": "Do not invent a location identifier.",
    }
    behavior = ["Do not invent entity, location, or issue details."]
    reply = "Water is leaking from the ceiling. How should I report it?"

    with patch("app.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = _groq_response(reply)
        result = generate_next_user_turn(
            persona,
            [],
            scenario_context=context,
            behavior_constraints=behavior,
        )

    assert result["message"] == reply
    prompt = _prompt(groq)
    assert "Water is leaking from the ceiling." in prompt
    assert "Do not invent a location identifier." in prompt
    assert "Do not invent entity, location, or issue details." in prompt


def test_agent_provided_choice_is_allowed_when_scenario_permits_selection():
    persona = Persona(
        name="Alex",
        goal="Book any available appointment on Friday afternoon.",
        tone="polite",
    )
    transcript = [
        ConversationMessage(
            role="agent",
            content="Friday afternoon has 2 PM and 4 PM available.",
            turn_index=0,
        )
    ]
    options = [
        {"type": "button", "message": "2 PM"},
        {"type": "button", "message": "4 PM"},
    ]
    decision = {"action": "select_option", "option_index": 0, "message": "2 PM"}

    with patch("app.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = _groq_response(json.dumps(decision))
        result = decide_next_user_action(
            persona,
            transcript,
            options,
            scenario_context={"availability": "Any Friday afternoon time is acceptable."},
            behavior_constraints=["Choose one of the times offered by the agent."],
        )

    assert result["selected_option_index"] == 0
    assert result["message"] == "2 PM"
    assert "agent-provided choice may be selected" in _prompt(groq)


def test_contradictory_options_use_grounded_free_text_fallback():
    persona = Persona(name="Alex", goal="Receive a refund for the purchase.", tone="direct")
    transcript = [
        ConversationMessage(
            role="agent",
            content="Choose a resolution.",
            turn_index=0,
        )
    ]
    options = [
        {"type": "button", "message": "Replacement"},
        {"type": "button", "message": "Store credit"},
    ]
    payload = {
        "action": "free_text",
        "option_index": None,
        "message": "Neither option matches my request; I need a refund.",
    }

    with patch("app.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = _groq_response(json.dumps(payload))
        result = decide_next_user_action(
            persona,
            transcript,
            options,
            scenario_context={"resolution": "Refund required."},
            behavior_constraints=["Do not accept a replacement or store credit."],
        )

    assert result["selected_option_index"] is None
    assert result["message"] == payload["message"]
    prompt = _prompt(groq)
    assert "Refund required." in prompt
    assert "Do not accept a replacement or store credit." in prompt


@pytest.mark.parametrize(
    ("goal", "context", "agent_message", "reply"),
    [
        (
            "Arrange a consultation and learn the available schedule.",
            {"preferred_day": "Friday"},
            "Which day works for you?",
            "Friday works for me.",
        ),
        (
            "Request reimbursement for a damaged purchase.",
            {"item_condition": "The outer casing arrived cracked."},
            "What was damaged?",
            "The outer casing arrived cracked.",
        ),
        (
            "Get help regaining access to an account.",
            {"account_identifier": "Do not disclose or invent one."},
            "What is the account identifier?",
            "I cannot provide an account identifier.",
        ),
        (
            "Report a facilities issue and understand the process.",
            {"issue": "Water is leaking from the ceiling."},
            "What issue are you reporting?",
            "Water is leaking from the ceiling.",
        ),
    ],
)
def test_grounding_prompt_is_domain_neutral(goal, context, agent_message, reply):
    persona = Persona(name="Alex", goal=goal, tone="natural")
    transcript = [ConversationMessage(role="agent", content=agent_message, turn_index=0)]

    with patch("app.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = _groq_response(reply)
        result = generate_next_user_turn(
            persona,
            transcript,
            scenario_context=context,
            behavior_constraints=["Use only scenario-supported material facts."],
        )

    assert result["message"] == reply
    assert next(iter(context.values())) in _prompt(groq)
