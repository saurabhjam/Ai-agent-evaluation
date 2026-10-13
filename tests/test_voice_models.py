"""
Tests for app/models/voice.py and app/voice/converter.py.

These tests require:
  - pydantic (already in requirements.txt)
  - deepeval==2.0.9 (already in requirements.txt)

No paid API keys, no external services, no real audio processing.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

from app.models.voice import (
    HandoffEvent,
    SessionStatus,
    Speaker,
    ToolCall,
    ToolResult,
    VoiceConversation,
    VoiceEvent,
    VoiceEventType,
    VoiceSession,
    VoiceTurn,
)
from app.voice.converter import voice_to_normalized_conversation, voice_to_deepeval_test_case


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def simple_session() -> VoiceSession:
    now = datetime.now(timezone.utc)
    return VoiceSession(
        session_id="test-session-001",
        call_id="fake-call-001",
        channel="voice",
        started_at=now.isoformat(),
        ended_at=(now + timedelta(seconds=60)).isoformat(),
        status=SessionStatus.completed,
    )


@pytest.fixture
def two_turn_conversation(simple_session) -> VoiceConversation:
    return VoiceConversation(
        session=simple_session,
        turns=[
            VoiceTurn(
                speaker=Speaker.user,
                text="I need a refund for order A1029.",
                latency_ms=None,
            ),
            VoiceTurn(
                speaker=Speaker.agent,
                text="I can help with that. Could you confirm the order number?",
                latency_ms=350.0,
            ),
            VoiceTurn(
                speaker=Speaker.user,
                text="Yes, it is A1029.",
            ),
            VoiceTurn(
                speaker=Speaker.agent,
                text="Thank you. I have processed a full refund for order A1029.",
                latency_ms=420.0,
            ),
        ],
        events=[
            VoiceEvent(event_type=VoiceEventType.call_started),
            VoiceEvent(event_type=VoiceEventType.speech_started),
            VoiceEvent(event_type=VoiceEventType.speech_ended),
            VoiceEvent(event_type=VoiceEventType.response_started),
            VoiceEvent(event_type=VoiceEventType.response_completed),
            VoiceEvent(event_type=VoiceEventType.call_ended),
        ],
    )


# ===========================================================================
# 1. Voice model tests
# ===========================================================================

class TestVoiceModels:
    def test_speaker_enum_values(self):
        assert Speaker.user == "user"
        assert Speaker.agent == "agent"
        assert Speaker.system == "system"

    def test_session_status_enum_values(self):
        assert SessionStatus.pending == "pending"
        assert SessionStatus.active == "active"
        assert SessionStatus.completed == "completed"
        assert SessionStatus.failed == "failed"
        assert SessionStatus.timed_out == "timed_out"

    def test_voice_event_type_enum_values(self):
        assert VoiceEventType.call_started == "call_started"
        assert VoiceEventType.call_ended == "call_ended"
        assert VoiceEventType.interruption == "interruption"

    def test_voice_session_defaults(self):
        session = VoiceSession()
        assert session.channel == "voice"
        assert session.status == SessionStatus.pending
        assert session.session_id  # UUID auto-generated
        assert session.call_id is None

    def test_voice_turn_defaults(self):
        turn = VoiceTurn(speaker=Speaker.user, text="Hello")
        assert turn.turn_id  # UUID auto-generated
        assert not turn.interrupted
        assert turn.confidence is None
        assert turn.audio_path is None

    def test_voice_event_defaults(self):
        event = VoiceEvent(event_type=VoiceEventType.speech_started)
        assert event.event_id
        assert event.timestamp
        assert event.data is None

    def test_tool_call_model(self):
        tc = ToolCall(tool_name="check_order", arguments={"order_id": "A1029"})
        assert tc.tool_call_id
        assert tc.tool_name == "check_order"
        assert tc.arguments == {"order_id": "A1029"}

    def test_tool_result_model(self):
        tr = ToolResult(tool_name="check_order", result={"status": "eligible"}, success=True, latency_ms=50.0)
        assert tr.success
        assert tr.latency_ms == 50.0

    def test_handoff_event_model(self):
        h = HandoffEvent(requested=True, destination="billing-queue")
        assert h.handoff_id
        assert h.requested
        assert not h.completed
        assert h.destination == "billing-queue"

    def test_voice_session_with_all_fields(self, simple_session):
        assert simple_session.session_id == "test-session-001"
        assert simple_session.call_id == "fake-call-001"
        assert simple_session.status == SessionStatus.completed

    def test_voice_conversation_serializes_to_dict(self, two_turn_conversation):
        d = two_turn_conversation.model_dump()
        assert "session" in d
        assert "turns" in d
        assert "events" in d
        assert len(d["turns"]) == 4
        assert len(d["events"]) == 6


# ===========================================================================
# 2. VoiceConversation helper tests
# ===========================================================================

class TestVoiceConversationHelpers:
    def test_user_turns(self, two_turn_conversation):
        user = two_turn_conversation.user_turns()
        assert len(user) == 2
        assert all(t.speaker == Speaker.user for t in user)

    def test_agent_turns(self, two_turn_conversation):
        agents = two_turn_conversation.agent_turns()
        assert len(agents) == 2
        assert all(t.speaker == Speaker.agent for t in agents)

    def test_interruptions_none(self, two_turn_conversation):
        assert len(two_turn_conversation.interruptions()) == 0

    def test_interruptions_detected(self, simple_session):
        vc = VoiceConversation(
            session=simple_session,
            turns=[
                VoiceTurn(speaker=Speaker.user, text="But wait—", interrupted=True),
                VoiceTurn(speaker=Speaker.agent, text="Sorry, go ahead."),
            ],
        )
        assert len(vc.interruptions()) == 1

    def test_average_agent_latency(self, two_turn_conversation):
        avg = two_turn_conversation.average_agent_latency_ms()
        assert avg == pytest.approx(385.0, rel=1e-3)  # (350 + 420) / 2

    def test_average_agent_latency_none_when_missing(self, simple_session):
        vc = VoiceConversation(
            session=simple_session,
            turns=[
                VoiceTurn(speaker=Speaker.agent, text="Hi!"),  # no latency_ms
            ],
        )
        assert vc.average_agent_latency_ms() is None

    def test_duration_seconds(self, two_turn_conversation):
        dur = two_turn_conversation.duration_seconds()
        assert dur == pytest.approx(60.0, abs=1.0)

    def test_duration_seconds_none_when_missing_timestamps(self, simple_session):
        session = VoiceSession()  # no timestamps
        vc = VoiceConversation(session=session)
        assert vc.duration_seconds() is None


# ===========================================================================
# 3. Voice -> NormalizedConversation converter tests
# ===========================================================================

class TestVoiceToNormalizedConverter:
    def test_basic_conversion(self, two_turn_conversation):
        nc = voice_to_normalized_conversation(two_turn_conversation, run_id="run-1")
        assert nc.run_id == "run-1"
        assert nc.channel == "voice"
        assert nc.session_id == "test-session-001"

    def test_message_count(self, two_turn_conversation):
        nc = voice_to_normalized_conversation(two_turn_conversation)
        assert len(nc.messages) == 4

    def test_speaker_mapping(self, two_turn_conversation):
        nc = voice_to_normalized_conversation(two_turn_conversation)
        assert nc.messages[0].role == "simulated_user"
        assert nc.messages[1].role == "agent"
        assert nc.messages[2].role == "simulated_user"
        assert nc.messages[3].role == "agent"

    def test_content_preserved(self, two_turn_conversation):
        nc = voice_to_normalized_conversation(two_turn_conversation)
        assert nc.messages[0].content == "I need a refund for order A1029."
        assert nc.messages[1].content == "I can help with that. Could you confirm the order number?"

    def test_latency_in_metadata(self, two_turn_conversation):
        nc = voice_to_normalized_conversation(two_turn_conversation)
        agent_msg = nc.messages[1]  # first agent turn
        assert agent_msg.metadata is not None
        assert agent_msg.metadata["latency_ms"] == 350.0

    def test_session_times_preserved(self, two_turn_conversation):
        nc = voice_to_normalized_conversation(two_turn_conversation)
        assert nc.start_time == two_turn_conversation.session.started_at
        assert nc.end_time == two_turn_conversation.session.ended_at

    def test_metadata_contains_voice_fields(self, two_turn_conversation):
        nc = voice_to_normalized_conversation(two_turn_conversation)
        assert nc.metadata is not None
        assert "event_count" in nc.metadata
        assert nc.metadata["event_count"] == 6
        assert "average_latency_ms" in nc.metadata
        assert "scenario_id" not in nc.metadata

    def test_scenario_id_passed_to_metadata(self, two_turn_conversation):
        nc = voice_to_normalized_conversation(two_turn_conversation, scenario_id="test_scenario_123")
        assert nc.metadata is not None
        assert nc.metadata.get("scenario_id") == "test_scenario_123"

    def test_auto_run_id_generated(self, two_turn_conversation):
        nc = voice_to_normalized_conversation(two_turn_conversation)
        assert nc.run_id  # should be auto-generated UUID

    def test_empty_conversation(self, simple_session):
        vc = VoiceConversation(session=simple_session)
        nc = voice_to_normalized_conversation(vc)
        assert len(nc.messages) == 0

    def test_system_turn_mapping(self, simple_session):
        vc = VoiceConversation(
            session=simple_session,
            turns=[VoiceTurn(speaker=Speaker.system, text="Call connected.")],
        )
        nc = voice_to_normalized_conversation(vc)
        assert nc.messages[0].role == "system"


# ===========================================================================
# 4. Voice -> DeepEval test case converter
# ===========================================================================

class TestVoiceToDeepEvalConverter:
    def test_produces_conversational_test_case(self, two_turn_conversation):
        from deepeval.test_case import ConversationalTestCase
        tc = voice_to_deepeval_test_case(two_turn_conversation)
        assert isinstance(tc, ConversationalTestCase)

    def test_turns_count(self, two_turn_conversation):
        from deepeval.test_case import ConversationalTestCase, LLMTestCase
        tc = voice_to_deepeval_test_case(two_turn_conversation)
        assert len(tc.turns) == 2  # 2 user-agent exchange pairs

    def test_turn_content(self, two_turn_conversation):
        tc = voice_to_deepeval_test_case(two_turn_conversation)
        assert tc.turns[0].input == "I need a refund for order A1029."
        assert tc.turns[0].actual_output == "I can help with that. Could you confirm the order number?"

    def test_empty_conversation_still_produces_test_case(self, simple_session):
        from deepeval.test_case import ConversationalTestCase
        vc = VoiceConversation(session=simple_session)
        tc = voice_to_deepeval_test_case(vc)
        assert isinstance(tc, ConversationalTestCase)
        assert len(tc.turns) == 1  # minimal fallback turn
