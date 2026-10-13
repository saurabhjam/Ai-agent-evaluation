from __future__ import annotations

from app.calling.conversation_evidence import ConversationEvidence, EvidenceArtifact
from app.calling.models import CallProvider, CallTranscriptTurn, NormalizedCallTranscript, TranscriptSpeaker


def test_conversation_evidence_serializes_vendor_neutral_fields():
    transcript = NormalizedCallTranscript(
        session_id="session-1",
        run_id="run-1",
        turns=[
            CallTranscriptTurn(
                speaker=TranscriptSpeaker.customer,
                text="Hello",
                turn_index=0,
            )
        ],
    )
    artifact = EvidenceArtifact(
        session_id="session-1",
        name="recording_url",
        artifact_type="recording_url",
        remote_url="https://provider.example/recording",
        provider=CallProvider.custom,
    )

    evidence = ConversationEvidence(
        session_id="session-1",
        run_id="run-1",
        provider=CallProvider.custom,
        provider_name="mock",
        provider_call_id="call-1",
        provider_metadata={"region": "test"},
        transcript=transcript,
        attachments=[artifact],
        rag_context=["Policy context"],
    )

    data = evidence.model_dump(mode="json")

    assert data["provider"] == "custom"
    assert data["provider_name"] == "mock"
    assert data["provider_call_id"] == "call-1"
    assert data["provider_metadata"] == {"region": "test"}
    assert data["attachments"][0]["name"] == "recording_url"
    assert data["rag_context"] == ["Policy context"]


def test_conversation_evidence_effective_transcript_from_turns():
    evidence = ConversationEvidence(
        session_id="session-1",
        run_id="run-1",
        transcript_turns=[
            CallTranscriptTurn(
                speaker=TranscriptSpeaker.agent,
                text="Hi",
                turn_index=0,
            )
        ],
    )

    transcript = evidence.effective_transcript()

    assert transcript.session_id == "session-1"
    assert transcript.run_id == "run-1"
    assert transcript.turns[0].text == "Hi"
    assert transcript.source == "conversation_evidence"
