from __future__ import annotations

from app.calling.conversation_evidence import ConversationEvidence
from app.calling.conversation_normalizer import ConversationNormalizer
from app.calling.models import (
    CallProvider,
    CallTranscriptTurn,
    NormalizedCallTranscript,
    TranscriptSpeaker,
)


def test_conversation_normalizer_outputs_existing_normalized_conversation():
    transcript = NormalizedCallTranscript(
        session_id="session-1",
        run_id="run-1",
        source="provider_json",
        turns=[
            CallTranscriptTurn(
                speaker=TranscriptSpeaker.customer,
                text="Book an appointment",
                turn_index=0,
                confidence=0.9,
            ),
            CallTranscriptTurn(
                speaker=TranscriptSpeaker.agent,
                text="Done",
                turn_index=1,
                confidence=0.95,
            ),
        ],
    )
    evidence = ConversationEvidence(
        session_id="session-1",
        run_id="run-1",
        provider=CallProvider.custom,
        provider_name="mock",
        provider_call_id="call-1",
        transcript=transcript,
        rag_context=["Appointments require a date."],
    )

    normalized = ConversationNormalizer().normalize(evidence, scenario_id="appointment")

    assert normalized.run_id == "run-1"
    assert normalized.session_id == "session-1"
    assert normalized.channel == "calling"
    assert [message.role for message in normalized.messages] == ["simulated_user", "agent"]
    assert normalized.messages[0].content == "Book an appointment"
    assert normalized.retrieval_context == ["Appointments require a date."]
    assert normalized.metadata["scenario_id"] == "appointment"
    assert normalized.metadata["provider_name"] == "mock"
    assert normalized.metadata["provider_call_id"] == "call-1"
    assert normalized.metadata["event_count"] == 0
