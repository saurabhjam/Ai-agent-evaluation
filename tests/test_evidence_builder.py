from __future__ import annotations

from app.calling.conversation_evidence import EvidenceArtifact
from app.calling.evidence_builder import EvidenceBuilder
from app.calling.models import (
    CallDirection,
    CallEvent,
    CallEventType,
    CallProvider,
    CallSession,
    CallTranscriptTurn,
    NormalizedCallTranscript,
    TranscriptSpeaker,
)


def test_evidence_builder_combines_session_outputs():
    session = CallSession(
        session_id="session-1",
        run_id="run-1",
        direction=CallDirection.outbound,
        provider=CallProvider.custom,
        provider_name="mock",
        provider_call_id="call-1",
        provider_metadata={"simulated": True},
    )
    transcript = NormalizedCallTranscript(
        session_id="session-1",
        run_id="run-1",
        turns=[
            CallTranscriptTurn(
                speaker=TranscriptSpeaker.customer,
                text="Need help",
                turn_index=0,
            )
        ],
    )
    event = CallEvent(session_id="session-1", event_type=CallEventType.call_created)
    artifact = EvidenceArtifact(
        session_id="session-1",
        name="events.json",
        artifact_type="events",
    )

    evidence = EvidenceBuilder().build(
        session=session,
        events=[event],
        transcript=transcript,
        artifacts=[artifact],
        rag_context=["RAG"],
    )

    assert evidence.session_id == "session-1"
    assert evidence.provider_name == "mock"
    assert evidence.provider_call_id == "call-1"
    assert evidence.provider_metadata == {"simulated": True}
    assert evidence.events == [event]
    assert evidence.transcript is transcript
    assert evidence.attachments[0].name == "events.json"
    assert evidence.rag_context == ["RAG"]
