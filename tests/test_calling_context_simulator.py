from unittest.mock import Mock, patch
import json

import pytest

from app.calling.models import CallTranscriptTurn, TranscriptSpeaker
from app.calling.simulator import generate_next_user_turn
from app.schemas import Persona


def turn(speaker, text):
    return CallTranscriptTurn(speaker=TranscriptSpeaker(speaker), text=text, turn_index=0)


@pytest.mark.parametrize("question,answer", [
    ("Could you please share your phone number?", "My phone number is 555-123-4567."),
    ("Your name is Rahul Sharma and your phone number is 555-123-4567. Is everything correct?", "Yes, that's correct."),
    ("I just want to confirm your phone number. Did you mean 555-123-4567?", "Yes, 555-123-4567."),
    ("Sorry, could you repeat that?", "555-123-4567."),
])
def test_latest_question_and_existing_details_reach_groq(question, answer):
    history = [
        turn("agent", "May I have your name?"),
        turn("customer", "My name is Rahul Sharma."),
        turn("agent", "What is your phone number?"),
        turn("customer", "555-123-4567."),
        turn("agent", question),
    ]
    response = Mock()
    response.choices = [Mock(message=Mock(content=answer))]
    with patch("app.calling.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = response
        result = generate_next_user_turn(
            Persona(name="Rahul Sharma", goal="Book a routine dental appointment", tone="polite"), history,
        )
    messages = groq.return_value.chat.completions.create.call_args.kwargs["messages"]
    assert messages[1:] == [
        {"role": "user" if t.speaker == TranscriptSpeaker.agent else "assistant", "content": t.text}
        for t in history
    ]
    assert messages[-1]["content"] == question
    assert result == {"message": answer, "attachments": None}


def test_first_question_does_not_restart_goal_and_empty_output_fails():
    response = Mock()
    response.choices = [Mock(message=Mock(content=""))]
    with patch("app.calling.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = response
        with pytest.raises(RuntimeError, match="empty content"):
            generate_next_user_turn(
                Persona(name="Rahul Sharma", goal="Book a dental appointment", tone="polite"),
                [turn("agent", "May I have your name?")],
            )
    messages = groq.return_value.chat.completions.create.call_args.kwargs["messages"]
    assert messages[-1] == {"role": "user", "content": "May I have your name?"}


def test_runner_sends_and_records_generated_text_without_reusing_name():
    from app.calling.models import CallDirection, CallStatus
    from app.calling.voice_conversation_runner import VoiceConversationRunner
    from app.calling.voice_transport import VoiceTransportSession

    transport = Mock(spec=["connect", "receive_text", "send_text", "hang_up"])
    transport.receive_text.side_effect = ["May I have your name?", "Could you please share your phone number?"]
    answers = ["My name is Rahul Sharma.", "My phone number is 555-123-4567."]
    responses = []
    for answer in answers:
        response = Mock()
        response.choices = [Mock(message=Mock(content=answer))]
        responses.append(response)
    with patch("app.calling.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.side_effect = responses
        result = VoiceConversationRunner(max_turns=2).run(
            persona=Persona(name="Rahul Sharma", goal="Book a dental appointment", tone="polite"),
            transport=transport,
            session=VoiceTransportSession(transport_name="test", transport_call_id="test", direction=CallDirection.inbound, status=CallStatus.in_progress),
            session_id="test", run_id="test",
        )
    assert [call.args[0] for call in transport.send_text.call_args_list] == answers
    assert [t.text for t in result.turns if t.speaker == TranscriptSpeaker.customer] == answers
    second_prompt = groq.return_value.chat.completions.create.call_args_list[1].kwargs["messages"]
    assert second_prompt[-2:] == [
        {"role": "assistant", "content": answers[0]},
        {"role": "user", "content": "Could you please share your phone number?"},
    ]


def test_calling_loader_preserves_configured_facts_without_changing_shared_schema():
    from app.calling.ui_api import _load_scenario

    scenario = _load_scenario("scenarios/appointment_inbound_calling.yaml")
    import yaml
    from pathlib import Path

    configured = yaml.safe_load((Path(__file__).resolve().parents[1] / "scenarios/appointment_inbound_calling.yaml").read_text())
    configured["persona"]["goal"] = configured["persona"]["goal"].strip()
    assert scenario.persona.model_dump() == configured["persona"]
    assert "phone_number" not in Persona.model_validate(configured["persona"]).model_dump()


@pytest.mark.parametrize("question,answer", [
    ("May I have your full name?", "Morgan Reed."),
    ("Could you please share your phone number?", "02079460958."),
    ("Please clarify your phone number.", "02079460958."),
    ("Which date do you prefer?", "November 12, 2027."),
    ("What time do you prefer?", "2:30 PM."),
    ("Morgan Reed, 02079460958, November 12, 2027 at 2:30 PM. Is that correct?", "Yes, that's correct."),
    ("What is your membership code?", "CL-842."),
])
def test_complete_arbitrary_scenario_and_latest_question_ground_model_request(question, answer):
    from app.calling.scenario import CallingPersona

    persona = CallingPersona(
        name="Morgan Reed", goal="Arrange a vehicle inspection. Provide details only when requested.",
        tone="polite", edge_case="Clarify only the requested detail; briefly confirm correct summaries.",
        phone_number="02079460958", preferred_date="November 12, 2027",
        preferred_time="2:30 PM", membership_code="CL-842",
    )
    response = Mock()
    response.choices = [Mock(message=Mock(content=answer))]
    history = [turn("agent", "How can I help?"), turn("customer", "Arrange a vehicle inspection."), turn("agent", question)]
    with patch("app.calling.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = response
        result = generate_next_user_turn(persona, history)
    groq.return_value.chat.completions.create.assert_called_once()
    messages = groq.return_value.chat.completions.create.call_args.kwargs["messages"]
    instructions, facts = messages[0]["content"].split("Complete scenario persona (JSON):\n")
    assert json.loads(facts) == persona.model_dump()
    assert "do not invent it" in instructions
    assert "only the information requested" in instructions
    assert "choose a fictional" not in instructions
    assert messages[-1] == {"role": "user", "content": question}
    assert result["message"] == answer


def test_generated_text_reaches_tts_unchanged():
    from app.calling.models import CallDirection, CallStatus
    from app.calling.voice_conversation_runner import VoiceConversationRunner
    from app.calling.voice_transport import VoiceTransportSession

    transport = Mock(spec=["connect", "receive_text", "send_audio", "hang_up"])
    transport.receive_text.return_value = "Please clarify your phone number."
    tts = Mock()
    tts.synthesize.return_value = b"audio"
    response = Mock()
    response.choices = [Mock(message=Mock(content="02079460958."))]
    with patch("app.calling.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = response
        result = VoiceConversationRunner(max_turns=1, tts_provider=tts).run(
            persona=Persona(name="Morgan Reed", goal="Arrange a vehicle inspection", tone="polite"),
            transport=transport,
            session=VoiceTransportSession(transport_name="test", transport_call_id="test", direction=CallDirection.inbound, status=CallStatus.in_progress),
            session_id="test", run_id="test",
        )
    tts.synthesize.assert_called_once_with("02079460958.")
    assert result.turns[-1].text == "02079460958."
    transport.send_audio.assert_called_once_with(b"audio", turn_index=0)


@pytest.mark.parametrize("history,generated", [
    ([turn("agent", "Hello")], "I'd like to book an appointment."),
    ([turn("agent", "May I have your full name?"),
      turn("customer", "Rahul Sharma."),
      turn("agent", "Could you please share your phone number?")], "9876543210."),
    ([turn("agent", "Could you please share your phone number?"),
      turn("customer", "9876543210."),
      turn("agent", "Did you mean 987650043210? Please clarify your phone number.")], "9876543210."),
])
def test_disclosure_contract_and_exact_generated_text(history, generated):
    """Check request construction and text handoff, not live model compliance."""
    from app.calling.ui_api import _load_scenario

    persona = _load_scenario("scenarios/appointment_inbound_calling.yaml").persona
    response = Mock()
    response.choices = [Mock(message=Mock(content=generated))]
    with patch("app.calling.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = response
        result = generate_next_user_turn(persona, history)

    messages = groq.return_value.chat.completions.create.call_args.kwargs["messages"]
    instructions, facts_json = messages[0]["content"].split("Complete scenario persona (JSON):\n")
    facts = json.loads(facts_json)
    assert facts == persona.model_dump(mode="json")
    assert facts["phone_number"] == "9876543210"
    assert "only when asked" in facts["goal"]
    assert "Do not volunteer" in facts["edge_case"]
    assert "only the information requested" in instructions
    assert "do not invent it" in instructions
    assert "without reintroducing yourself" in instructions
    assert "start with" in instructions and "initial request in the goal" in instructions
    assert messages[1:] == [
        {"role": "user" if t.speaker == TranscriptSpeaker.agent else "assistant", "content": t.text}
        for t in history
    ]
    assert result["message"] == generated
    if history[-1].text == "Hello":
        assert persona.name not in result["message"]
        assert facts["phone_number"] not in result["message"]
        assert facts["preferred_date"] not in result["message"]
        assert facts["preferred_time"] not in result["message"]
    else:
        assert result["message"] == facts["phone_number"] + "."
