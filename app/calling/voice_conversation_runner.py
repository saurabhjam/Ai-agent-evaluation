"""Evaluator-side voice conversation runner for calling evaluations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional
import io
import logging
import wave

from app.calling.models import (
    CallTranscriptTurn,
    RawCallTranscript,
    TranscriptSpeaker,
)
from app.calling.voice_transport import VoiceTransport, VoiceTransportSession
from app.schemas import Persona
from app.simulator import generate_next_user_turn


logger = logging.getLogger(__name__)

SimulatorFn = Callable[[Persona, list[Any]], dict[str, Any]]


@dataclass
class VoiceConversationRunner:
    """
    Owns evaluator-side conversation lifecycle and turn-taking.

    VoiceTransport stays low-level: it creates/owns the media session. This
    runner owns the AI user simulator, STT/TTS handoff points, transcript
    assembly, and stop conditions.
    """

    simulator: SimulatorFn = generate_next_user_turn
    max_turns: int = 8
    receive_timeout_seconds: float = 30.0
    tts_provider: Optional[Any] = None
    stt_provider: Optional[Any] = None

    def run(
        self,
        *,
        persona: Persona,
        transport: VoiceTransport,
        session: VoiceTransportSession,
        session_id: str,
        run_id: str,
    ) -> RawCallTranscript:
        turns: list[CallTranscriptTurn] = []

        transport.connect(session)
        try:
            for turn_index in range(self.max_turns):
                agent_text = self._receive_agent_text(transport)
                if agent_text:
                    turns.append(
                        CallTranscriptTurn(
                            speaker=TranscriptSpeaker.agent,
                            text=agent_text,
                            turn_index=len(turns),
                        )
                    )

                user_turn = self.simulator(persona, turns)
                user_text = (user_turn.get("message") or "").strip()
                if not user_text or "[END_CONVERSATION]" in user_text:
                    break

                self._send_user_text(transport, user_text, turn_index=turn_index)
                turns.append(
                    CallTranscriptTurn(
                        speaker=TranscriptSpeaker.customer,
                        text=user_text,
                        turn_index=len(turns),
                    )
                )
        finally:
            transport.hang_up(session)

        return RawCallTranscript(
            session_id=session_id,
            run_id=run_id,
            turns=turns,
            source="voice_transport",
            metadata={
                "transport_name": session.transport_name,
                "transport_call_id": session.transport_call_id,
            },
        )

    def _send_user_text(self, transport: VoiceTransport, text: str, *, turn_index: int) -> None:
        if hasattr(transport, "send_text"):
            transport.send_text(text, turn_index=turn_index)
            return
        if not self.tts_provider or not hasattr(transport, "send_audio"):
            raise RuntimeError(
                f"{transport.__class__.__name__} cannot send evaluator speech; "
                "provide send_text() or send_audio() with a TTS provider."
            )
        transport.send_audio(self.tts_provider.synthesize(text), turn_index=turn_index)

    def _receive_agent_text(self, transport: VoiceTransport) -> str:
        if hasattr(transport, "receive_text"):
            return str(transport.receive_text(timeout_seconds=self.receive_timeout_seconds) or "").strip()
        if not hasattr(transport, "receive_audio"):
            return ""
        audio = transport.receive_audio(timeout_seconds=self.receive_timeout_seconds)
        info = _audio_info(audio)
        logger.info(
            "receive_agent_text audio bytes=%d wav_duration_seconds=%s sample_rate=%s channels=%s bits_per_sample=%s",
            info["byte_length"],
            info["duration_seconds"],
            info["sample_rate"],
            info["channels"],
            info["bits_per_sample"],
        )
        if not self.stt_provider:
            raise RuntimeError(
                f"{transport.__class__.__name__} returned audio but no STT provider is configured."
            )
        transcript = self.stt_provider.transcribe(audio)
        return str(getattr(transcript, "text", transcript) or "").strip()


def _audio_info(audio_bytes: bytes) -> dict[str, Any]:
    info: dict[str, Any] = {
        "byte_length": len(audio_bytes or b""),
        "duration_seconds": None,
        "sample_rate": None,
        "channels": None,
        "bits_per_sample": None,
    }
    if not audio_bytes:
        return info
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
            sample_rate = wav.getframerate()
            frames = wav.getnframes()
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            info.update(
                {
                    "duration_seconds": frames / sample_rate if sample_rate else None,
                    "sample_rate": sample_rate,
                    "channels": channels,
                    "bits_per_sample": sample_width * 8,
                }
            )
    except (wave.Error, EOFError):
        logger.info("receive_agent_text audio is not a readable WAV container")
    return info
