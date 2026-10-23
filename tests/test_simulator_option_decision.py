from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.conversation import ConversationMessage
from app.schemas import Persona
from app.simulator import _parse_action_decision, _validated_action_result, decide_next_user_action


def _groq_response(payload: dict):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
    )


@pytest.mark.parametrize(
    ("goal", "agent_message", "options", "selected_index"),
    [
        (
            "Arrange a consultation with a specialist.",
            "Choose the next available scheduling slot.",
            ["Review billing statements", "Friday at 3 PM", "Contact sales"],
            1,
        ),
        (
            "Resolve a purchase return and receive reimbursement.",
            "First identify which purchase this concerns.",
            ["Track shipment", "Select transaction 123", "Browse products"],
            1,
        ),
        (
            "Regain access to my account credentials.",
            "Identity confirmation is required before continuing.",
            ["View subscription", "Send verification code", "Upgrade plan"],
            1,
        ),
        (
            "Have a facilities problem corrected at my residence.",
            "Choose the location where help is needed.",
            ["Select residence A", "View occupancy analytics", "Show highest charges"],
            0,
        ),
    ],
)
def test_semantic_decision_allows_indirect_goal_advancing_steps(
    goal, agent_message, options, selected_index
):
    persona = Persona(name="Jordan", goal=goal, tone="polite")
    transcript = [ConversationMessage(role="agent", content=agent_message, turn_index=0)]
    components = [
        {"type": "button", "label": value, "message": value}
        for value in options
    ]
    decision_payload = {
        "action": "select_option",
        "option_index": selected_index,
        "message": options[selected_index],
    }

    with patch("app.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = _groq_response(decision_payload)
        result = decide_next_user_action(persona, transcript, components)

    assert result["selected_option_index"] == selected_index
    assert result["message"] == options[selected_index]
    request = groq.return_value.chat.completions.create.call_args.kwargs
    prompt = "\n".join(item["content"] for item in request["messages"])
    assert goal in prompt
    assert agent_message in prompt
    assert all(option in prompt for option in options)
    assert "word overlap" in prompt
    assert "authoritative objective" in prompt


def test_no_relevant_option_uses_goal_directed_free_text_fallback():
    persona = Persona(
        name="Jordan",
        goal="Correct an unexpected charge on my account.",
        tone="direct",
    )
    transcript = [
        ConversationMessage(role="simulated_user", content="I need help correcting a charge.", turn_index=0),
        ConversationMessage(role="agent", content="Would you like to browse upgrades instead?", turn_index=1),
    ]
    components = [
        {"type": "button", "message": "View premium plans"},
        {"type": "button", "message": "Read product news"},
    ]
    payload = {
        "action": "free_text",
        "option_index": None,
        "message": "No, I still need help correcting the unexpected charge.",
    }

    with patch("app.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = _groq_response(payload)
        result = decide_next_user_action(persona, transcript, components)

    assert result["selected_option_index"] is None
    assert "unexpected charge" in result["message"]
    assert groq.return_value.chat.completions.create.call_count == 1


def test_agent_redirect_does_not_replace_persona_goal_in_decision_context():
    persona = Persona(
        name="Jordan",
        goal="Obtain a copy of a prior invoice.",
        tone="concise",
    )
    transcript = [
        ConversationMessage(role="agent", content="Let us switch to opening a new sales account.", turn_index=0)
    ]
    components = [{"type": "button", "message": "Open new account"}]
    payload = {
        "action": "free_text",
        "option_index": None,
        "message": "I only need a copy of my prior invoice.",
    }

    with patch("app.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = _groq_response(payload)
        result = decide_next_user_action(persona, transcript, components)

    assert result["selected_option_index"] is None
    request = groq.return_value.chat.completions.create.call_args.kwargs
    system = request["messages"][0]["content"]
    assert "goal is immutable" in system
    assert "Reject options that redirect" in system


def test_invalid_interactive_decision_uses_grounded_fallback_instead_of_first_option():
    persona = Persona(name="Jordan", goal="Complete the configured task.", tone="neutral")
    components = [{"type": "button", "message": "Unrelated action"}]
    with patch("app.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.side_effect = [
            _groq_response({"action": "select_option", "option_index": 99}),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="I still need help with my configured task."))]),
        ]
        result = decide_next_user_action(persona, [], components)

    assert result["selected_option_index"] is None
    assert result["message"] == "I still need help with my configured task."
    assert groq.return_value.chat.completions.create.call_count == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"action":"select_option","option_index":1}', {"action": "select_option", "option_index": 1}),
        ('{"action":"free_text","text":"Continue my request."}', {"action": "free_text", "option_index": None, "text": "Continue my request."}),
        ('```json\n{"action":"free_text","text":"Continue."}\n```', {"action": "free_text", "option_index": None, "text": "Continue."}),
        ('  { "action" : "select_option", "option_index" : 0 }  ', {"action": "select_option", "option_index": 0}),
        ('{"action":"free_text","message":"Legacy response."}', {"action": "free_text", "option_index": None, "text": "Legacy response."}),
    ],
)
def test_action_decision_parser_accepts_only_harmless_format_normalization(raw, expected):
    assert _parse_action_decision(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "{}",
        '{"action":"free_text","text":""}',
        '{"action":"select_option"}',
        '{"action":"select_option","option_index":9}',
        '{"action":"other","text":"hello"}',
        "not json",
    ],
)
def test_unusable_decisions_are_rejected_without_selecting_an_option(raw):
    options = [{"index": 0, "label": "First", "message": "First"}]
    with pytest.raises(RuntimeError):
        decision = _parse_action_decision(raw)
        _validated_action_result(decision, options)


def test_empty_successful_decision_uses_one_grounded_fallback_call():
    persona = Persona(name="Jordan", goal="Submit the configured request.", tone="concise")
    transcript = [ConversationMessage(role="agent", content="Choose a destination.", turn_index=0)]
    options = [
        {"type": "button", "message": "Unsupported identifier 100"},
        {"type": "button", "message": "Unsupported identifier 200"},
    ]
    context = {"identifier": "Unknown; do not invent an identifier."}
    behavior = ["Explain that the identifier is unavailable rather than inventing it."]

    empty = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None), finish_reason="stop")]
    )
    grounded = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="I do not have the identifier available."))]
    )
    with patch("app.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.side_effect = [empty, grounded]
        result = decide_next_user_action(
            persona,
            transcript,
            options,
            scenario_context=context,
            behavior_constraints=behavior,
        )

    assert result == {
        "message": "I do not have the identifier available.",
        "attachments": None,
        "selected_option_index": None,
    }
    assert result["message"] not in {option["message"] for option in options}
    assert groq.return_value.chat.completions.create.call_count == 2
    fallback_prompt = "\n".join(
        item["content"]
        for item in groq.return_value.chat.completions.create.call_args_list[1].kwargs["messages"]
    )
    assert "Unknown; do not invent an identifier." in fallback_prompt
    assert behavior[0] in fallback_prompt


def test_provider_failure_is_not_converted_to_grounded_fallback():
    class ProviderRateLimitError(Exception):
        pass

    persona = Persona(name="Jordan", goal="Complete the configured task.", tone="neutral")
    error = ProviderRateLimitError("429 rate limit")
    with patch("app.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.side_effect = error
        with pytest.raises(ProviderRateLimitError, match="429 rate limit"):
            decide_next_user_action(
                persona,
                [],
                [{"type": "button", "message": "Option"}],
                scenario_context={"fact": "configured"},
                behavior_constraints=["Use configured facts only."],
            )

    assert groq.return_value.chat.completions.create.call_count == 1


def test_bounded_fallback_raises_clear_error_when_generation_is_also_empty():
    persona = Persona(name="Jordan", goal="Complete the configured task.", tone="neutral")
    empty = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None), finish_reason="stop")]
    )
    with patch("app.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.side_effect = [empty, empty]
        with pytest.raises(RuntimeError, match="grounded fallback generation did not produce"):
            decide_next_user_action(
                persona,
                [],
                [{"type": "button", "message": "Option"}],
                scenario_context={"fact": "configured"},
                behavior_constraints=["Use configured facts only."],
            )

    assert groq.return_value.chat.completions.create.call_count == 2
