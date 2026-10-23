from __future__ import annotations

from unittest.mock import Mock, patch

from app.calling.models import CallDirection, CallStatus, CallTranscriptTurn, TranscriptSpeaker
from app.calling.scenario import CallingScenario
from app.calling.simulator import (
    AgentTurnIntentType,
    StatefulCallingSimulator,
    _interpret_agent_turn,
)
from app.calling.voice_conversation_runner import VoiceConversationRunner
from app.calling.voice_transport import VoiceTransport, VoiceTransportSession


def _turn(speaker: str, text: str):
    return CallTranscriptTurn(
        speaker=TranscriptSpeaker(speaker),
        text=text,
        turn_index=0,
    )


def _scenario(*, mode="normal", volunteer=None, field_overrides=None):
    fields = {
        "name": {"aliases": ["name", "full name"]},
        "contact_code": {"aliases": ["contact code", "code"], "speak_as": "digits"},
        "preferred_day": {"aliases": ["date", "day"]},
    }
    fields.update(field_overrides or {})
    return CallingScenario(
        scenario_id="generic-caller",
        agent={"channel": "calling", "adapter": "test"},
        persona={
            "name": "Avery Stone",
            "contact_code": "90710",
            "preferred_day": "March 8, 2027",
            "goal": "Arrange a service visit using the configured details",
            "tone": "calm and concise",
            "edge_case": "Answer the current request without unrelated details",
        },
        calling_simulator={
            "mode": mode,
            "opening_message": "I'd like to arrange a service visit.",
            "volunteer_fields": volunteer or [],
            "fields": fields,
        },
    )


def _phone_scenario(*, mode="normal", initial_value=None):
    field = {"aliases": ["phone", "phone number"], "speak_as": "digits"}
    if initial_value is not None:
        field["initial_value"] = initial_value
    return CallingScenario(
        scenario_id="generic-phone-caller",
        agent={"channel": "calling", "adapter": "test"},
        persona={
            "name": "Avery Stone",
            "phone_number": "5551234567",
            "preferred_date": "March 8, 2027",
            "preferred_time": "10:00 AM",
            "goal": "Arrange a service visit",
            "tone": "concise",
        },
        calling_simulator={
            "mode": mode,
            "fields": {
                "name": {"aliases": ["name", "full name"]},
                "phone_number": field,
                "preferred_date": {"aliases": ["date", "preferred date"]},
                "preferred_time": {"aliases": ["time", "preferred time"]},
            },
        },
    )


def _intent(simulator, text):
    return _interpret_agent_turn(text, [_turn("agent", text)], simulator.state)


def _reply(simulator, question, template):
    response = Mock()
    response.choices = [Mock(message=Mock(content=template))]
    with patch("app.calling.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value = response
        result = simulator(simulator.scenario.persona, [_turn("agent", question)])
    return result, groq.return_value.chat.completions.create.call_args.kwargs["messages"]


def test_name_request_discloses_only_name():
    simulator = StatefulCallingSimulator(_scenario())
    result, messages = _reply(simulator, "May I have your full name?", "Sure, {{fact:name}}.")

    assert result["message"] == "Sure, Avery Stone."
    assert "90710" not in result["message"]
    assert result["disclosed_fields"] == ["name"]
    assert "contact_code" not in messages[0]["content"].split("Allowed placeholders:", 1)[1]


def test_configured_code_is_canonical_and_has_separate_spoken_value():
    simulator = StatefulCallingSimulator(_scenario())
    result, _ = _reply(simulator, "What is your contact code?", "It is {{fact:contact_code}}.")

    assert result["message"] == "It is 90710."
    assert result["spoken_message"] == "It is nine zero seven one zero."
    assert simulator.state.facts["contact_code"].canonical == "90710"


def test_date_and_multiple_requested_fields_use_configured_values():
    simulator = StatefulCallingSimulator(_scenario())
    result, _ = _reply(simulator, "What date works for you?", "{{fact:preferred_day}} works.")
    assert result["message"] == "March 8, 2027 works."

    simulator = StatefulCallingSimulator(_scenario())
    result, _ = _reply(
        simulator,
        "Please provide your name and contact code.",
        "{{fact:name}}, {{fact:contact_code}}.",
    )
    assert result["message"] == "Avery Stone, 90710."
    assert result["disclosed_fields"] == ["name", "contact_code"]


def test_context_retention_policy_can_volunteer_explicit_fields():
    simulator = StatefulCallingSimulator(_scenario(mode="context_retention", volunteer=["contact_code"]))
    result, _ = _reply(
        simulator,
        "May I have your name?",
        "{{fact:name}} and {{fact:contact_code}}.",
    )
    assert result["message"] == "Avery Stone and 90710."


def test_refusal_policy_withholds_configured_field():
    scenario = _scenario()
    scenario.calling_simulator.mode = "refusal"
    scenario.calling_simulator.refuse_fields = ["contact_code"]
    simulator = StatefulCallingSimulator(scenario)
    result, _ = _reply(simulator, "What is your contact code?", "I'd rather not provide that information.")

    assert result["message"] == "I'd rather not provide that information."
    assert result["disclosed_fields"] == []


def test_correction_policy_supplies_initial_then_authoritative_value():
    simulator = StatefulCallingSimulator(
        _scenario(mode="correction", field_overrides={"contact_code": {
            "aliases": ["contact code"], "speak_as": "digits", "initial_value": "90711"
        }})
    )
    first, _ = _reply(simulator, "What is your contact code?", "{{fact:contact_code}}.")
    second, _ = _reply(simulator, "Please correct your contact code.", "{{fact:contact_code}}.")

    assert first["message"] == "90711."
    assert second["message"] == "90710."
    assert simulator.state.corrected_fields == {"contact_code"}


def test_clarification_policy_can_supply_incomplete_then_full_value():
    simulator = StatefulCallingSimulator(
        _scenario(mode="clarification", field_overrides={"contact_code": {
            "aliases": ["contact code"], "speak_as": "digits", "initial_value": "907"
        }})
    )
    first, _ = _reply(simulator, "What is your contact code?", "{{fact:contact_code}}.")
    second, _ = _reply(simulator, "Could you clarify that?", "{{fact:contact_code}}.")

    assert first["message"] == "907."
    assert second["message"] == "90710."


def test_role_reversal_and_invented_values_use_grounded_fallback():
    simulator = StatefulCallingSimulator(_scenario())
    role_result, _ = _reply(simulator, "What is your name?", "May I have your name?")
    assert role_result["message"] == "Avery Stone."

    simulator = StatefulCallingSimulator(_scenario())
    invented_result, _ = _reply(simulator, "What is your contact code?", "My code is 111999.")
    assert invented_result["message"] == "90710."


def test_bare_placeholders_are_rejected_and_replaced_with_requested_fact():
    simulator = StatefulCallingSimulator(_scenario())
    result, _ = _reply(
        simulator,
        "What is your contact code?",
        "My name is {} and my code is {}.",
    )

    assert result["message"] == "90710."
    assert result["simulator_contract"]["fallback_triggered"] is True
    assert result["simulator_contract"]["valid"] is True


def test_compound_fact_name_does_not_match_an_isolated_word():
    simulator = StatefulCallingSimulator(_scenario())
    simulator.state.turn_number = 1
    result, _ = _reply(
        simulator,
        "Thank you for arranging the service visit.",
        "Okay.",
    )

    assert result["message"] == "Okay."
    assert result["simulator_contract"]["requested_fields"] == []
    assert result["disclosed_fields"] == []


def test_wrong_fact_placeholder_falls_back_to_only_the_requested_fact():
    simulator = StatefulCallingSimulator(_scenario())
    result, _ = _reply(
        simulator,
        "What is your contact code?",
        "{{fact:name}}.",
    )

    assert result["message"] == "90710."
    assert result["disclosed_fields"] == ["contact_code"]


def test_omitted_placeholder_uses_requested_fact_fallback():
    simulator = StatefulCallingSimulator(_scenario())
    result, _ = _reply(simulator, "What is your contact code?", "Thank you.")

    assert result["message"] == "90710."
    assert result["simulator_contract"]["fallback_triggered"] is True


def test_previously_disclosed_name_cannot_replace_repeated_requested_code():
    simulator = StatefulCallingSimulator(_scenario())
    _reply(simulator, "What is your name?", "{{fact:name}}.")
    first, _ = _reply(simulator, "What is your contact code?", "{{fact:name}}.")
    second, _ = _reply(simulator, "Please repeat your contact code.", "{{fact:contact_code}}.")

    assert first["message"] == "90710."
    assert second["message"] == "90710."
    assert first["disclosed_fields"] == ["contact_code"]
    assert second["disclosed_fields"] == ["contact_code"]


def test_fact_is_not_disclosed_when_final_contract_is_invalid():
    simulator = StatefulCallingSimulator(_scenario())
    with patch("app.calling.simulator._fallback_template", return_value="Okay."):
        result, _ = _reply(simulator, "What is your contact code?", "Thank you.")

    assert result["simulator_contract"]["valid"] is False
    assert result["disclosed_fields"] == []
    assert "contact_code" not in simulator.state.disclosed_fields


def test_same_phone_keyword_has_distinct_request_confirm_and_acknowledge_intents():
    simulator = StatefulCallingSimulator(_phone_scenario())

    request = _intent(simulator, "What is your phone number?")
    confirm = _intent(simulator, "Your phone number is 5551234567, correct?")
    acknowledge = _intent(simulator, "I have your phone number.")

    assert request.intent == AgentTurnIntentType.REQUEST_FACT
    assert request.requested_fields == ("phone_number",)
    assert confirm.intent == AgentTurnIntentType.CONFIRM_FACT
    assert confirm.mentioned_fields == ("phone_number",)
    assert confirm.requested_fields == ()
    assert acknowledge.intent == AgentTurnIntentType.ACKNOWLEDGE_FACT
    assert acknowledge.requested_fields == ()


def test_correction_offer_uses_correction_policy_without_becoming_fact_request():
    simulator = StatefulCallingSimulator(_phone_scenario(mode="correction", initial_value="5551234000"))
    first, _ = _reply(simulator, "What is your phone number?", "{{fact:phone_number}}.")
    intent = _intent(simulator, "Would you like to correct your phone number?")
    corrected, _ = _reply(
        simulator,
        "Would you like to correct your phone number?",
        "{{fact:phone_number}}.",
    )

    assert first["message"] == "5551234000."
    assert intent.intent == AgentTurnIntentType.REQUEST_CORRECTION
    assert intent.requested_fields == ()
    assert corrected["message"] == "5551234567."


def test_closing_summary_mentions_all_fields_but_requests_none():
    simulator = StatefulCallingSimulator(_phone_scenario())
    text = (
        "I have your name, phone number, preferred date and preferred time. "
        "Is there anything else I can help you with?"
    )
    intent = _intent(simulator, text)
    simulator.state.turn_number = 1
    result, _ = _reply(simulator, text, "No, that's all. Thank you.")

    assert intent.intent == AgentTurnIntentType.CLOSING
    assert set(intent.mentioned_fields) == {"name", "phone_number", "preferred_date", "preferred_time"}
    assert intent.requested_fields == ()
    assert result["disclosed_fields"] == []
    assert result["simulator_contract"]["allowed_fields"] == []


def test_full_name_request_and_thank_you_name_are_not_conflated():
    simulator = StatefulCallingSimulator(_phone_scenario())
    request = _intent(simulator, "May I have your full name?")
    acknowledgement = _intent(simulator, "Thank you Rahul.")

    assert request.intent == AgentTurnIntentType.REQUEST_FACT
    assert request.requested_fields == ("name",)
    assert acknowledgement.intent == AgentTurnIntentType.ACKNOWLEDGE_FACT
    assert acknowledgement.requested_fields == ()


def test_fact_confirmation_confirms_without_redisclosing_phone():
    simulator = StatefulCallingSimulator(_phone_scenario())
    simulator.state.turn_number = 1
    result, _ = _reply(
        simulator,
        "Your phone number is 5551234567, correct?",
        "Yes, that's correct.",
    )

    assert result["message"] == "Yes, that's correct."
    assert result["simulator_contract"]["intent"] == "confirm_fact"
    assert result["simulator_contract"]["requested_fields"] == []
    assert result["disclosed_fields"] == []


def test_state_and_history_persist_across_turns():
    simulator = StatefulCallingSimulator(_scenario())
    _reply(simulator, "What is your name?", "{{fact:name}}.")
    _reply(simulator, "What is your contact code?", "{{fact:contact_code}}.")

    assert simulator.state.turn_number == 2
    assert simulator.state.disclosed_fields == {"name", "contact_code"}
    assert simulator.state.requested_fields == ["contact_code"]


class _TextTransport(VoiceTransport):
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def connect(self, session):
        return None

    def receive_text(self, timeout_seconds=30):
        return self.responses.pop(0) if self.responses else ""

    def send_text(self, text, turn_index=0):
        self.sent.append(text)


class _IncompleteAudioTransport(VoiceTransport):
    def __init__(self):
        self.sent = []

    def receive_audio(self, timeout_seconds=30):
        return b"partial"

    def last_utterance_complete(self):
        return False

    def send_audio(self, audio, turn_index=0):
        self.sent.append(audio)


def _session():
    return VoiceTransportSession(
        transport_name="test",
        transport_call_id="call-1",
        direction=CallDirection.inbound,
        status=CallStatus.in_progress,
    )


def test_empty_and_duplicate_agent_utterances_do_not_duplicate_customer_response():
    calls = []

    def simulator(persona, transcript):
        calls.append(list(transcript))
        return {"message": "Customer reply."}

    transport = _TextTransport(["", "Same complete turn", "Same complete turn"])
    VoiceConversationRunner(simulator=simulator, max_turns=3).run(
        persona=_scenario().persona,
        transport=transport,
        session=_session(),
        session_id="session-1",
        run_id="run-1",
    )

    assert len(calls) == 1
    assert transport.sent == ["Customer reply."]


def test_incomplete_audio_never_reaches_stt_or_simulator():
    simulator = Mock()
    stt = Mock()
    VoiceConversationRunner(simulator=simulator, stt_provider=stt, max_turns=1).run(
        persona=_scenario().persona,
        transport=_IncompleteAudioTransport(),
        session=_session(),
        session_id="session-1",
        run_id="run-1",
    )

    stt.transcribe.assert_not_called()
    simulator.assert_not_called()


def test_explicit_interruption_policy_may_use_partial_utterance():
    scenario = _scenario(mode="interruption")
    simulator = StatefulCallingSimulator(scenario)
    stt = Mock()
    stt.transcribe.return_value = Mock(text="Partial agent request")
    tts = Mock()
    tts.synthesize.return_value = b"customer-audio"
    transport = _IncompleteAudioTransport()

    VoiceConversationRunner(
        simulator=simulator,
        stt_provider=stt,
        tts_provider=tts,
        max_turns=1,
    ).run(
        persona=scenario.persona,
        transport=transport,
        session=_session(),
        session_id="session-1",
        run_id="run-1",
    )

    stt.transcribe.assert_called_once_with(b"partial")
    assert transport.sent == [b"customer-audio"]


def test_runner_sends_spoken_value_but_records_canonical_value():
    transport = _IncompleteAudioTransport()
    transport.last_utterance_complete = lambda: True
    stt = Mock()
    stt.transcribe.return_value = Mock(text="What is your contact code?")
    tts = Mock()
    tts.synthesize.return_value = b"customer-audio"

    def simulator(persona, transcript):
        return {"message": "90710.", "spoken_message": "nine zero seven one zero."}

    transcript = VoiceConversationRunner(
        simulator=simulator,
        stt_provider=stt,
        tts_provider=tts,
        max_turns=1,
    ).run(
        persona=_scenario().persona,
        transport=transport,
        session=_session(),
        session_id="session-1",
        run_id="run-1",
    )

    tts.synthesize.assert_called_once_with("nine zero seven one zero.")
    assert transcript.turns[-1].text == "90710."


def test_runner_preserves_simulator_contract_violations_as_calling_metadata():
    transport = _TextTransport(["What is your contact code?"])

    def simulator(persona, transcript):
        return {
            "message": "Wrong customer reply.",
            "simulator_contract": {"valid": False, "requested_fields": ["contact_code"]},
        }

    transcript = VoiceConversationRunner(simulator=simulator, max_turns=1).run(
        persona=_scenario().persona,
        transport=transport,
        session=_session(),
        session_id="session-1",
        run_id="run-1",
    )

    assert transcript.metadata["simulator_contract_violations"] == [
        {"turn_id": 0, "valid": False, "requested_fields": ["contact_code"]}
    ]
