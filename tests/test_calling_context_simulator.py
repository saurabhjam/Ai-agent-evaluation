from __future__ import annotations

from unittest.mock import Mock, patch

from app.calling.models import CallTranscriptTurn, TranscriptSpeaker
from app.calling.scenario import CallingPersona
from app.calling.simulator import StatefulCallingSimulator
from app.calling.ui_api import _load_scenario


def _turn(speaker: str, text: str):
    return CallTranscriptTurn(
        speaker=TranscriptSpeaker(speaker),
        text=text,
        turn_index=0,
    )


def test_calling_loader_preserves_facts_and_structured_policy():
    scenario = _load_scenario("scenarios/appointment_inbound_calling.yaml")

    assert scenario.persona.phone_number == "9876543210"
    assert scenario.persona.preferred_date == "October 20, 2026"
    assert scenario.calling_simulator.mode == "normal"
    assert scenario.calling_simulator.fields["phone_number"].speak_as == "digits"


def test_shared_persona_schema_is_not_changed_by_calling_extras():
    persona = CallingPersona(
        name="Morgan Reed",
        goal="Arrange a vehicle inspection using configured details",
        tone="polite",
        membership_code="CL-842",
    )

    assert persona.membership_code == "CL-842"
    assert "membership_code" in persona.model_dump()


def test_groq_receives_latest_complete_agent_text_but_not_authoritative_values():
    scenario = _load_scenario("scenarios/appointment_inbound_calling.yaml")
    simulator = StatefulCallingSimulator(scenario)
    response = Mock()
    response.choices = [Mock(message=Mock(content="Sure, {{fact:name}}."))]
    history = [
        _turn("agent", "Hello"),
        _turn("customer", "I'd like to make a booking."),
        _turn("agent", "May I have your full name?"),
    ]

    with patch("app.calling.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = response
        result = simulator(scenario.persona, history)

    prompt = groq.return_value.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "Latest complete agent utterance: May I have your full name?" in prompt
    assert "Rahul Sharma" not in prompt
    assert "9876543210" not in prompt
    assert result["message"] == "Sure, Rahul Sharma."


def test_summary_confirmation_does_not_redisclose_named_fields():
    scenario = _load_scenario("scenarios/appointment_inbound_calling.yaml")
    simulator = StatefulCallingSimulator(scenario)
    response = Mock()
    response.choices = [Mock(message=Mock(content="Yes, that's correct."))]

    with patch("app.calling.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = response
        result = simulator(
            scenario.persona,
            [_turn("agent", "Your name and phone number are correct, right?")],
        )

    assert result["message"] == "Yes, that's correct."
    assert result["disclosed_fields"] == []


def test_greeting_discloses_intent_without_persona_details():
    scenario = _load_scenario("scenarios/appointment_inbound_calling.yaml")
    simulator = StatefulCallingSimulator(scenario)

    result = simulator(scenario.persona, [_turn("agent", "Hello, how can I help?")])

    assert result["message"] == "Hi, I'd like to schedule a routine dental appointment."
    assert scenario.persona.name not in result["message"]
    assert scenario.persona.phone_number not in result["message"]
    assert scenario.persona.preferred_date not in result["message"]
    assert scenario.persona.preferred_time not in result["message"]
