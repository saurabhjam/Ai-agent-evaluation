from __future__ import annotations

from app.calling.models import CallTranscriptTurn, NormalizedCallTranscript, TranscriptSpeaker
from app.calling.normalizer import call_transcript_to_normalized_conversation


def test_call_transcript_normalizes_to_existing_conversation_model():
    transcript = NormalizedCallTranscript(
        session_id="call-session-1",
        run_id="run-1",
        language="en",
        source="stt",
        turns=[
            CallTranscriptTurn(
                speaker=TranscriptSpeaker.customer,
                text="I want to check my order.",
                turn_index=0,
                confidence=0.92,
                start_time=0.0,
                end_time=1.5,
            ),
            CallTranscriptTurn(
                speaker=TranscriptSpeaker.agent,
                text="Sure, I can help with that.",
                turn_index=1,
                confidence=0.95,
                start_time=1.7,
                end_time=3.0,
            ),
            CallTranscriptTurn(
                speaker=TranscriptSpeaker.system,
                text="Call completed.",
                turn_index=2,
            ),
        ],
    )

    normalized = call_transcript_to_normalized_conversation(
        transcript,
        scenario_id="order-status",
        retrieval_context=["Orders can be checked with an order ID."],
    )

    assert normalized.run_id == "run-1"
    assert normalized.session_id == "call-session-1"
    assert normalized.channel == "calling"
    assert normalized.retrieval_context == ["Orders can be checked with an order ID."]
    assert [message.role for message in normalized.messages] == ["simulated_user", "agent", "system"]
    assert normalized.messages[0].content == "I want to check my order."
    assert normalized.messages[0].metadata["confidence"] == 0.92
    assert normalized.metadata["scenario_id"] == "order-status"
    assert normalized.metadata["source"] == "stt"


def test_call_transcript_normalizer_handles_empty_transcript():
    transcript = NormalizedCallTranscript(session_id="call-session-1", run_id="run-1")

    normalized = call_transcript_to_normalized_conversation(transcript)

    assert normalized.messages == []
    assert normalized.channel == "calling"
    assert normalized.status == "completed"
