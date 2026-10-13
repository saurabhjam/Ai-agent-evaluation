from __future__ import annotations

from app.calling.models import CallDirection, CallStatus, TranscriptSpeaker
from app.calling.voice_conversation_runner import VoiceConversationRunner
from app.calling.voice_transport import VoiceTransport, VoiceTransportSession
from app.schemas import Persona


class TextVoiceTransport(VoiceTransport):
    def __init__(self):
        self.sent: list[str] = []
        self.responses = ["Hello, how can I help?"]

    def send_text(self, text: str, turn_index: int = 0) -> None:
        self.sent.append(text)

    def receive_text(self, timeout_seconds: float = 30.0) -> str:
        return self.responses.pop(0) if self.responses else ""


def test_voice_conversation_runner_produces_raw_call_transcript():
    def simulator(persona, transcript):
        return {"message": "I need a dental appointment."}

    transport = TextVoiceTransport()
    session = VoiceTransportSession(
        transport_name="text",
        transport_call_id="transport-call-1",
        direction=CallDirection.outbound,
        status=CallStatus.in_progress,
    )

    transcript = VoiceConversationRunner(simulator=simulator, max_turns=1).run(
        persona=Persona(name="Rahul", goal="Book an appointment", tone="polite"),
        transport=transport,
        session=session,
        session_id="session-1",
        run_id="run-1",
    )

    assert transcript.source == "voice_transport"
    assert transport.sent == ["I need a dental appointment."]
    assert [turn.speaker for turn in transcript.turns] == [
        TranscriptSpeaker.agent,
        TranscriptSpeaker.customer,
    ]
