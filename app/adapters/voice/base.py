"""
Abstract VoiceAdapter interface.

This is the voice-channel equivalent of app/adapters/base.py (AgentAdapter).

Responsibilities of a VoiceAdapter implementation:
  - Establish / tear down the session with the voice agent under test.
  - Send simulated user audio (or text that gets converted to audio).
  - Receive and transcribe the agent's audio response.
  - Record all events, latencies, and tool calls in vendor-neutral types.
  - Return a fully populated VoiceConversation at the end of the session.

Responsibilities that do NOT belong here:
  - DeepEval scoring
  - Pass/Fail decisions
  - Business rule validation
  - Vendor-specific object types in return values
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from app.models.voice import (
    VoiceConversation,
    VoiceEvent,
    VoiceTurn,
)


class VoiceAdapterCapabilities:
    """
    Feature flags for a concrete VoiceAdapter.

    Evaluation code uses these to decide which evidence fields to inspect
    and which metrics to enable.
    """
    supports_audio_recording: bool = False   # can produce local .wav files
    supports_latency_measurement: bool = True
    supports_interruption_detection: bool = False
    supports_tool_calls: bool = False
    supports_handoff_detection: bool = False
    supports_real_time_streaming: bool = False
    supports_telephony: bool = False         # True only for real phone adapters


class VoiceAdapter(ABC):
    """
    Abstract base for all voice adapters (local, fake, WebSocket, telephony).

    Concrete sub-classes implement communication with a specific voice agent
    technology stack, but must always return vendor-neutral types.
    """

    @property
    def capabilities(self) -> VoiceAdapterCapabilities:
        return VoiceAdapterCapabilities()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def start_session(self, config: Optional[dict[str, Any]] = None) -> str:
        """
        Start a new voice session.

        Returns the session_id (a framework UUID, not a vendor ID).
        The adapter records the session start time and updates session status.
        """
        ...

    @abstractmethod
    def end_session(self) -> VoiceConversation:
        """
        End the voice session and return the full normalised conversation.

        The adapter must:
          1. Signal the voice agent that the call is ending.
          2. Flush any buffered events / turns.
          3. Set session.ended_at and session.status = completed / failed.
          4. Return the complete VoiceConversation.
        """
        ...

    # ------------------------------------------------------------------
    # Audio I/O
    # ------------------------------------------------------------------

    @abstractmethod
    def send_audio(self, audio_bytes: bytes, turn_index: int = 0) -> None:
        """
        Send raw audio bytes representing a user utterance to the voice agent.

        The adapter is responsible for encoding / streaming the audio in
        whatever format the target agent expects.

        Parameters
        ----------
        audio_bytes:
            Raw PCM or compressed audio bytes to send.
        turn_index:
            Logical turn counter used for logging and artifact naming.
        """
        ...

    @abstractmethod
    def receive_audio(self, timeout_seconds: float = 30.0) -> bytes:
        """
        Block until the agent produces an audio response, then return it.

        Returns raw audio bytes.  The adapter must also append the
        corresponding VoiceTurn (speaker=agent) to its internal state.
        """
        ...

    # ------------------------------------------------------------------
    # Text convenience methods (built on send/receive audio via TTS/STT)
    # ------------------------------------------------------------------

    def send_text(self, text: str, turn_index: int = 0) -> None:
        """
        Convert text to audio (via the adapter's TTS provider) and send it.

        Default implementation raises NotImplementedError.  Adapters that
        bundle a TTS component (e.g. LocalVoiceAdapter) override this.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement send_text(). "
            "Use send_audio() directly or use a TTS-capable adapter."
        )

    def receive_text(self, timeout_seconds: float = 30.0) -> str:
        """
        Receive agent audio and transcribe it to text (via the adapter's STT).

        Default implementation raises NotImplementedError.  Adapters that
        bundle an STT component override this.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement receive_text(). "
            "Use receive_audio() and transcribe separately, or use an "
            "STT-capable adapter."
        )

    # ------------------------------------------------------------------
    # Evidence accessors
    # ------------------------------------------------------------------

    @abstractmethod
    def get_transcript(self) -> list[VoiceTurn]:
        """Return all VoiceTurn objects recorded so far."""
        ...

    @abstractmethod
    def get_events(self) -> list[VoiceEvent]:
        """Return all VoiceEvent objects recorded so far."""
        ...

    @abstractmethod
    def get_session(self) -> Any:
        """Return the current VoiceSession metadata object."""
        ...

    @abstractmethod
    def get_conversation(self) -> VoiceConversation:
        """Return the current (possibly incomplete) VoiceConversation."""
        ...

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Optional: establish a persistent connection to the voice agent backend.

        For adapters that do not require a persistent connection (e.g. simple
        REST-based voice APIs), this can be a no-op.
        """

    def disconnect(self) -> None:
        """
        Optional: close the persistent connection cleanly.
        """
