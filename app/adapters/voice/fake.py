"""
FakeVoiceAdapter — for framework-level testing only.

This adapter simulates the full voice pipeline without any external service:

  1. User text is "spoken" by writing a minimal WAV file (stdlib wave module).
  2. A scripted agent response is returned (no LLM call needed).
  3. The agent "speaks" by writing another WAV file.
  4. Latency is simulated deterministically.
  5. All events are recorded in the normalised vocabulary.

This is NOT a mock of any real voice agent vendor.  Its purpose is to verify
that the evaluation framework pipeline (VoiceAdapter -> VoiceConversation ->
converter -> DeepEval) works end-to-end without a phone or cloud account.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
import wave
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.adapters.voice.base import VoiceAdapter, VoiceAdapterCapabilities
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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default scripted responses (overridable via config)
# ---------------------------------------------------------------------------

_DEFAULT_RESPONSES: list[str] = [
    "Hello! How can I help you today?",
    "I understand. Let me look into that for you.",
    "I can certainly help with that. Could you provide more details?",
    "Thank you for the information. I'll process your request now.",
    "Is there anything else I can help you with?",
]

# Fake audio: 0.25-second silent WAV at 16 kHz, 16-bit mono
_SAMPLE_RATE = 16_000
_SILENCE_DURATION_S = 0.25
_NUM_SAMPLES = int(_SAMPLE_RATE * _SILENCE_DURATION_S)
_SILENT_PCM = struct.pack(f"<{_NUM_SAMPLES}h", *([0] * _NUM_SAMPLES))


def _make_wav_bytes(pcm_data: bytes, sample_rate: int = _SAMPLE_RATE) -> bytes:
    """Wrap raw 16-bit mono PCM data in a minimal WAV container."""
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)          # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

class FakeVoiceAdapterCapabilities(VoiceAdapterCapabilities):
    supports_audio_recording: bool = True
    supports_latency_measurement: bool = True
    supports_interruption_detection: bool = False
    supports_tool_calls: bool = False
    supports_handoff_detection: bool = False
    supports_real_time_streaming: bool = False
    supports_telephony: bool = False


# ---------------------------------------------------------------------------
# FakeVoiceAdapter
# ---------------------------------------------------------------------------

class FakeVoiceAdapter(VoiceAdapter):
    """
    Fake voice adapter for testing the evaluation framework.

    Config keys (all optional):
      audio_dir      str   Base directory for WAV artifacts
                           (default: "artifacts/voice")
      responses      list  Ordered list of scripted agent replies
      latency_ms     float Simulated agent response latency (default: 120)
      sample_rate    int   WAV sample rate (default: 16000)
    """

    def __init__(self, config: Optional[dict[str, Any]] = None):
        self.config = config or {}
        self._audio_dir = Path(
            self.config.get("audio_dir", "artifacts/voice")
        )
        self._responses: list[str] = list(
            self.config.get("responses", _DEFAULT_RESPONSES)
        )
        self._simulated_latency_ms: float = float(
            self.config.get("latency_ms", 120.0)
        )
        self._sample_rate: int = int(
            self.config.get("sample_rate", _SAMPLE_RATE)
        )

        # Internal state
        self._session: Optional[VoiceSession] = None
        self._session_dir: Optional[Path] = None
        self._turns: list[VoiceTurn] = []
        self._events: list[VoiceEvent] = []
        self._tool_calls: list[ToolCall] = []
        self._tool_results: list[ToolResult] = []
        self._handoff_events: list[HandoffEvent] = []
        self._turn_index: int = 0
        self._response_index: int = 0

    @property
    def capabilities(self) -> FakeVoiceAdapterCapabilities:
        return FakeVoiceAdapterCapabilities()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start_session(self, config: Optional[dict[str, Any]] = None) -> str:
        session_id = str(uuid.uuid4())
        call_id = f"fake-call-{session_id[:8]}"

        self._session = VoiceSession(
            session_id=session_id,
            call_id=call_id,
            channel="voice",
            started_at=datetime.now(timezone.utc).isoformat(),
            status=SessionStatus.active,
        )

        # Create per-session audio directory
        self._session_dir = self._audio_dir / session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[FakeVoiceAdapter] Session started: {session_id}")

        self._record_event(VoiceEventType.call_started)
        return session_id

    def end_session(self) -> VoiceConversation:
        if self._session is None:
            raise RuntimeError("end_session() called before start_session()")

        self._session.ended_at = datetime.now(timezone.utc).isoformat()
        self._session.status = SessionStatus.completed
        self._record_event(VoiceEventType.call_ended)
        logger.info(f"[FakeVoiceAdapter] Session ended: {self._session.session_id}")
        return self.get_conversation()

    # ------------------------------------------------------------------
    # Audio I/O
    # ------------------------------------------------------------------

    def send_audio(self, audio_bytes: bytes, turn_index: int = 0) -> None:
        """
        Accepts raw audio bytes representing a user utterance.

        In the fake adapter, we write the audio to disk and record a VoiceTurn
        with a placeholder transcription.  No actual STT is performed — the
        text must be supplied via send_text() for real transcription.
        """
        if self._session is None:
            raise RuntimeError("send_audio() called before start_session()")

        audio_path = self._save_audio(audio_bytes, speaker="user", index=turn_index)

        self._record_event(VoiceEventType.speech_started)
        turn = VoiceTurn(
            speaker=Speaker.user,
            text="[audio-only: no STT performed by FakeVoiceAdapter]",
            audio_path=str(audio_path),
        )
        self._turns.append(turn)
        self._record_event(VoiceEventType.speech_ended)

    def receive_audio(self, timeout_seconds: float = 30.0) -> bytes:
        """
        Return a silent WAV as a stand-in for the agent's audio response.

        Also appends the matching VoiceTurn (speaker=agent) with the
        scripted text response.
        """
        if self._session is None:
            raise RuntimeError("receive_audio() called before start_session()")

        self._record_event(VoiceEventType.response_started)

        # Simulate latency
        time.sleep(self._simulated_latency_ms / 1000.0)
        latency_ms = self._simulated_latency_ms

        # Pick scripted response
        response_text = self._responses[
            self._response_index % len(self._responses)
        ]
        self._response_index += 1

        # Write agent WAV (silent placeholder)
        wav_bytes = _make_wav_bytes(_SILENT_PCM, self._sample_rate)
        audio_path = self._save_audio(
            wav_bytes, speaker="agent", index=self._turn_index
        )

        turn = VoiceTurn(
            speaker=Speaker.agent,
            text=response_text,
            latency_ms=latency_ms,
            audio_path=str(audio_path),
        )
        self._turns.append(turn)
        self._turn_index += 1

        self._record_event(VoiceEventType.response_completed)
        return wav_bytes

    # ------------------------------------------------------------------
    # Text convenience (fake TTS/STT — just records text, makes WAV file)
    # ------------------------------------------------------------------

    def send_text(self, text: str, turn_index: int = 0) -> None:
        """
        Simulate 'speaking' text by writing a silent WAV and recording the turn.

        In a real LocalVoiceAdapter this would call PiperTTS.
        """
        if self._session is None:
            raise RuntimeError("send_text() called before start_session()")

        wav_bytes = _make_wav_bytes(_SILENT_PCM, self._sample_rate)
        audio_path = self._save_audio(wav_bytes, speaker="user", index=turn_index)

        self._record_event(VoiceEventType.speech_started)
        turn = VoiceTurn(
            speaker=Speaker.user,
            text=text,
            audio_path=str(audio_path),
        )
        self._turns.append(turn)
        self._record_event(VoiceEventType.speech_ended)

    def receive_text(self, timeout_seconds: float = 30.0) -> str:
        """
        Simulate agent response: returns scripted text + saves WAV artifact.
        """
        self.receive_audio(timeout_seconds=timeout_seconds)
        # The turn was appended by receive_audio(); return its text.
        agent_turns = [t for t in self._turns if t.speaker == Speaker.agent]
        if agent_turns:
            return agent_turns[-1].text
        return ""

    # ------------------------------------------------------------------
    # Evidence accessors
    # ------------------------------------------------------------------

    def get_transcript(self) -> list[VoiceTurn]:
        return list(self._turns)

    def get_events(self) -> list[VoiceEvent]:
        return list(self._events)

    def get_session(self) -> Optional[VoiceSession]:
        return self._session

    def get_conversation(self) -> VoiceConversation:
        if self._session is None:
            raise RuntimeError("get_conversation() called before start_session()")
        return VoiceConversation(
            session=self._session,
            turns=list(self._turns),
            events=list(self._events),
            tool_calls=list(self._tool_calls),
            tool_results=list(self._tool_results),
            handoff_events=list(self._handoff_events),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_event(self, event_type: VoiceEventType, data: Optional[dict] = None) -> None:
        self._events.append(VoiceEvent(event_type=event_type, data=data))

    def _save_audio(self, audio_bytes: bytes, speaker: str, index: int) -> Path:
        """Write audio bytes to the per-session artifact directory."""
        filename = f"{speaker}_{index:03d}.wav"
        path = self._session_dir / filename
        path.write_bytes(audio_bytes)
        logger.debug(f"[FakeVoiceAdapter] Saved audio: {path}")
        return path
