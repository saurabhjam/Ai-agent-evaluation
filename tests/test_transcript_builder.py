from __future__ import annotations

from app.calling.audio_metadata import AudioMetadata
from app.calling.models import CallDirection, CallProvider, CallSession
from app.calling.transcript_builder import TranscriptBuilder
from app.calling.transcription import RawTranscript, RawTranscriptSegment


def _session() -> CallSession:
    return CallSession(
        session_id="session-1",
        run_id="run-1",
        direction=CallDirection.outbound,
        provider=CallProvider.twilio,
        provider_name="twilio",
        provider_call_id="CA123",
    )


def test_transcript_builder_builds_provider_transcript():
    raw = RawTranscript(
        source="provider_transcript",
        provider_name="twilio",
        audio_metadata=AudioMetadata(duration_seconds=10.0, codec="wav"),
        segments=[
            RawTranscriptSegment(speaker="caller", text="Book appointment", start_time=0.0, end_time=1.0),
            RawTranscriptSegment(speaker="agent", text="Done", start_time=1.5, end_time=2.0),
        ],
    )

    transcript = TranscriptBuilder().build_transcript(
        session_id="session-1",
        run_id="run-1",
        raw_transcript=raw,
    )

    assert transcript.source == "provider_transcript"
    assert [turn.speaker.value for turn in transcript.turns] == ["customer", "agent"]
    assert transcript.metadata["provider_name"] == "twilio"
    assert transcript.metadata["audio_metadata"]["duration_seconds"] == 10.0


def test_transcript_builder_builds_manual_transcript_to_normalized_conversation():
    raw = RawTranscript(
        source="manual",
        segments=[
            RawTranscriptSegment(speaker="customer", text="Hello", start_time=0.0, end_time=1.0),
            RawTranscriptSegment(speaker="assistant", text="Hi", start_time=1.2, end_time=2.0),
        ],
    )

    conversation = TranscriptBuilder().build_conversation(
        session=_session(),
        raw_transcript=raw,
        scenario_id="manual-transcript",
        rag_context=["Greeting policy"],
    )

    assert conversation.channel == "calling"
    assert [message.role for message in conversation.messages] == ["simulated_user", "agent"]
    assert conversation.retrieval_context == ["Greeting policy"]
    assert conversation.metadata["scenario_id"] == "manual-transcript"


def test_transcript_builder_builds_evidence_through_evidence_builder():
    raw = RawTranscript(
        source="stt",
        provider_name="future-whisper",
        segments=[
            RawTranscriptSegment(speaker="speaker_0", text="Need help", start_time=0.0, end_time=1.0),
            RawTranscriptSegment(speaker="speaker_1", text="I can help", start_time=1.1, end_time=2.0),
        ],
    )

    evidence = TranscriptBuilder().build_evidence(session=_session(), raw_transcript=raw)

    assert evidence.transcript is not None
    assert evidence.transcript.source == "stt"
    assert len(evidence.transcript.turns) == 2
