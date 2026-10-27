from unittest.mock import Mock, patch

import pytest
import yaml

from app.calling.scenario import CallingScenario
from app.calling.simulator import StatefulCallingSimulator, _interpret_agent_turn
from app.calling.workflow_evidence import build_workflow_evidence
from app.calling.voice_conversation_runner import VoiceConversationRunner
from app.calling.voice_transport import VoiceTransport
from tests.test_calling_stateful_simulator import _session, _TextTransport, _turn


def scenario():
    from pathlib import Path
    return CallingScenario.model_validate(yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "scenarios/appointment_inbound_calling.yaml").read_text()
    ))


@pytest.mark.parametrize("question,field", [
    ("May I please have your full name?", "name"),
    ("May I have your full name?", "name"),
    ("Could you please tell me your full name?", "name"),
    ("Could you please let me know your preferred appointment date?", "preferred_date"),
    ("When would you like to schedule your appointment?", "preferred_date"),
    ("Is there a specific date you have in mind?", "preferred_date"),
    ("What time works for you?", "preferred_time"),
])
def test_live_request_variants_cannot_acknowledge_instead_of_answer(question, field):
    sim = StatefulCallingSimulator(scenario())
    sim.state.turn_number = 1
    with patch.object(sim, "_naturalize", return_value="Okay."):
        result = sim(sim.scenario.persona, [_turn("agent", question)])
    assert result["message"] == sim.state.facts[field].canonical + "."
    assert result["simulator_contract"]["requested_fields"] == [field]


def test_complete_offline_conversation_stops_before_generation_tts_or_send():
    sim = StatefulCallingSimulator(scenario())
    questions = [
        "Hello.", "May I please have your full name?", "What is your phone number?",
        "When would you like to schedule your appointment?", "What time works for you?",
        "Is there anything else I can help you with?",
        "You're welcome. Thank you for calling. Have a great day.",
    ]
    class AudioTransport(VoiceTransport):
        def __init__(self):
            self.responses = iter(questions)
            self.send_audio = Mock()
            self.hang_up = Mock()

        def receive_text(self, **kwargs):
            return next(self.responses)

    transport = AudioTransport()
    recorder = Mock()
    recorder.finalize.return_value = None
    tts = Mock()
    tts.synthesize.return_value = b"audio"
    with patch("app.calling.simulator.Groq") as groq:
        groq.return_value.chat.completions.create.return_value.choices = [Mock(message=Mock(content="Okay."))]
        result = VoiceConversationRunner(
            simulator=sim, max_turns=20, tts_provider=tts,
            audio_recorder_factory=lambda **kw: recorder,
        ).run(persona=sim.scenario.persona, transport=transport, session=_session(), session_id="s", run_id="r")
    assert result.metadata["completion_reason"] == "semantic_conversation_complete"
    assert transport.send_audio.call_count == 6
    assert len(result.turns) == 13
    assert result.turns[-1].text == questions[-1]
    assert sim.state.disclosed_fields == set(sim.state.facts)
    assert groq.return_value.chat.completions.create.call_count == 4
    assert tts.synthesize.call_count == 6
    transport.hang_up.assert_called_once()
    recorder.finalize.assert_called_once()
    assert result.metadata["conversation_lifecycle"]["transport_closed_at"]
    assert result.metadata["latency_turns"][0]["first_turn"] is True
    assert result.metadata["latency_turns"][1]["first_turn"] is False
    assert result.metadata["latency_turns"][0]["boundaries"]["clock_anchor_utc"]


def test_role_evidence_distinguishes_non_answer_from_supplied_fact():
    messages = [
        {"role": "agent", "content": "May I please have your full name?"},
        {"role": "simulated_user", "content": "Okay."},
        {"role": "agent", "content": "Could you tell me your full name?"},
        {"role": "simulated_user", "content": "Rahul Sharma."},
        {"role": "agent", "content": "May I have your full name?"},
    ]
    proof = build_workflow_evidence(scenario(), messages)
    assert proof[1]["missing_requested_fields"] == ["name"]
    assert proof[2]["justified_reasks"] == ["name"]
    assert proof[4]["previously_supplied_requests"] == ["name"]
    assert proof[4]["justified_reasks"] == []


def test_opening_disclosure_is_explicit_and_scenario_owned():
    config = scenario()
    proof = build_workflow_evidence(config, [
        {"role": "simulated_user", "content": config.calling_simulator.opening_message}
    ])
    assert "appointment_reason" in proof[0]["supplied_fields"]
    assert "request a routine" in config.persona.goal
    assert "explains why it cannot proceed" in config.persona.goal


def test_indirect_request_detection_is_not_appointment_specific():
    config = CallingScenario(
        scenario_id="parcel-collection", agent={"channel": "calling", "adapter": "mock"},
        persona={"name": "Taylor", "goal": "Request a collection", "tone": "brief", "collection_date": "March 8, 2027", "reference_code": "AB-72"},
        calling_simulator={"fields": {"collection_date": {"aliases": ["date"]}, "reference_code": {"aliases": ["reference code"]}}},
    )
    sim = StatefulCallingSimulator(config)
    assert _interpret_agent_turn("When would you like collection?", [], sim.state).requested_fields == ("collection_date",)
    assert _interpret_agent_turn("Could you let me know your reference code?", [], sim.state).requested_fields == ("reference_code",)
    assert not _interpret_agent_turn("When does the office open?", [], sim.state).requested_fields


def test_explicit_request_still_obeys_refusal_policy():
    config = scenario()
    config.calling_simulator.refuse_fields = ["name"]
    sim = StatefulCallingSimulator(config)
    result = sim(config.persona, [_turn("agent", "May I please have your full name?")])
    assert result["simulator_contract"]["action"] == "refuse"
    assert config.persona.name not in result["message"]
