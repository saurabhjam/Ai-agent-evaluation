"""
Local Voice Adapter — free / open-source development stack.

Provides:
  1. SpeechToTextProvider  — abstract STT interface
     FasterWhisperSTT      — concrete implementation (requires faster-whisper)

  2. TextToSpeechProvider  — abstract TTS interface
     PiperTTS              — concrete implementation (requires piper-tts)

  3. LocalVoiceAdapter     — a VoiceAdapter that wires a TTS + STT together
     and talks to a locally running voice agent via simple HTTP calls.

Design rules:
  - Neither FasterWhisper nor Piper is a hard import-time requirement.
    Both are imported lazily inside their class bodies so that the module
    can be imported (and the interfaces used) even when the libraries are
    not installed.
  - A future provider (e.g. DeepgramSTT, ElevenLabsTTS) simply sub-classes
    the relevant abstract base class — no changes to the adapter are needed.
  - This file contains ZERO DeepEval, ZERO scoring, ZERO business logic.
"""

from __future__ import annotations

import io
import logging
import os
import time
import uuid
import wave
import threading
import audioop
import struct
from abc import ABC, abstractmethod
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
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_SAMPLE_RATE = 16_000
_DEFAULT_MAX_STT_AUDIO_SECONDS = 60.0
_SILENCE_SAMPLES = int(_DEFAULT_SAMPLE_RATE * 0.1)
_SILENT_PCM = struct.pack(f"<{_SILENCE_SAMPLES}h", *([0] * _SILENCE_SAMPLES))


def _make_wav_bytes(pcm_data: bytes, sample_rate: int = _DEFAULT_SAMPLE_RATE) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def _inspect_audio_bytes(audio_bytes: bytes, *, fallback_sample_rate: int = _DEFAULT_SAMPLE_RATE) -> dict[str, Any]:
    info: dict[str, Any] = {
        "byte_length": len(audio_bytes or b""),
        "duration_seconds": None,
        "sample_rate": None,
        "channels": None,
        "bits_per_sample": None,
        "container": "unknown",
    }
    if not audio_bytes:
        return info
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
            sample_rate = wf.getframerate()
            frames = wf.getnframes()
            sample_width = wf.getsampwidth()
            info.update(
                {
                    "duration_seconds": frames / sample_rate if sample_rate else None,
                    "sample_rate": sample_rate,
                    "channels": wf.getnchannels(),
                    "bits_per_sample": sample_width * 8,
                    "container": "wav",
                    "pcm_samples": frames,
                    "pcm_bytes": frames * sample_width * wf.getnchannels(),
                }
            )
            silence_frames = 0
            block_frames = max(sample_rate // 50, 1)
            while True:
                block = wf.readframes(block_frames)
                if not block:
                    break
                if audioop.rms(block, sample_width) < 60:
                    silence_frames += len(block) // (sample_width * wf.getnchannels())
            info["rms_below_60_seconds"] = silence_frames / sample_rate if sample_rate else None
            return info
    except (wave.Error, EOFError):
        pass

    bytes_per_sample = 2
    channels = 1
    if fallback_sample_rate:
        info.update(
            {
                "duration_seconds": len(audio_bytes) / (fallback_sample_rate * channels * bytes_per_sample),
                "sample_rate": fallback_sample_rate,
                "channels": channels,
                "bits_per_sample": 16,
                "container": "assumed_raw_pcm_s16le",
            }
        )
    return info


# ===========================================================================
# Abstract STT provider
# ===========================================================================

class SpeechToTextProvider(ABC):
    """
    Abstract Speech-to-Text provider interface.

    Concrete implementations:
      FasterWhisperSTT   — local, free (faster-whisper library)
      DeepgramSTT        — cloud, paid (future)
      GoogleSTT          — cloud, paid (future)
      AzureSTT           — cloud, paid (future)
      ClientSTT          — pass-through to client's own STT (future)
    """

    @abstractmethod
    def transcribe(self, audio_bytes: bytes, sample_rate: int = 16_000) -> str:
        """
        Transcribe audio bytes to text.

        Parameters
        ----------
        audio_bytes:
            Raw WAV (or PCM) audio data.
        sample_rate:
            Sample rate of the audio in Hz.

        Returns
        -------
        str
            The transcribed text string.
        """
        ...

    def transcribe_file(self, audio_path: str) -> str:
        """
        Convenience method: transcribe audio from a file path.

        Default implementation reads the file and calls transcribe().
        """
        audio_bytes = Path(audio_path).read_bytes()
        return self.transcribe(audio_bytes)


# ===========================================================================
# Concrete STT: FasterWhisperSTT
# ===========================================================================

_WHISPER_MODEL_CACHE: dict[tuple[Any, ...], Any] = {}
_WHISPER_MODEL_CACHE_LOCK = threading.Lock()


class FasterWhisperSTT(SpeechToTextProvider):
    """
    STT provider backed by the faster-whisper library (local, free, CPU/GPU).

    Install:
        pip install faster-whisper

    This class imports faster_whisper lazily so that the module can be
    imported without the library installed (e.g. in CI without GPU).

    Raises ImportError only when transcribe() is actually called and the
    library is missing, giving a clear actionable message.
    """

    def __init__(self, model_size: str = "small", device: str = "cpu",
                 compute_type: str = "int8", language: Optional[str] = None,
                 max_audio_duration_seconds: float = _DEFAULT_MAX_STT_AUDIO_SECONDS,
                 cpu_threads: Optional[int] = None,
                 beam_size: int = 1):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.max_audio_duration_seconds = max_audio_duration_seconds
        # Cap CPU threads to 4 by default to prevent Intel MKL memory pool exhaustion
        self.cpu_threads = cpu_threads if cpu_threads is not None else min(4, os.cpu_count() or 1)
        self.beam_size = beam_size
        self._model = None  # lazy-loaded on first use

    def _get_model(self):
        cache_key = (self.model_size, self.device, self.compute_type, self.cpu_threads)
        with _WHISPER_MODEL_CACHE_LOCK:
            if cache_key in _WHISPER_MODEL_CACHE:
                logger.info("FasterWhisperSTT reusing cached Whisper model key=%s", cache_key)
                self._model = _WHISPER_MODEL_CACHE[cache_key]
                return self._model
            if self._model is not None:
                return self._model
            logger.info(
                "FasterWhisperSTT creating Whisper model name=%s device=%s compute_type=%s cpu_threads=%s",
                self.model_size,
                self.device,
                self.compute_type,
                self.cpu_threads,
            )
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise ImportError(
                    "FasterWhisperSTT requires 'faster-whisper' to be installed. "
                    "Run: pip install faster-whisper"
                ) from exc
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=self.cpu_threads,
            )
            _WHISPER_MODEL_CACHE[cache_key] = self._model
        return self._model

    def transcribe(self, audio_bytes: bytes, sample_rate: int = 16_000) -> str:
        """Transcribe WAV bytes using faster-whisper."""
        started = time.perf_counter()
        info = _inspect_audio_bytes(audio_bytes, fallback_sample_rate=sample_rate)
        logger.info(
            "LocalSTTProvider.transcribe audio bytes=%d wav_duration_seconds=%s sample_rate=%s channels=%s bits_per_sample=%s whisper_model=%s model_reused=%s",
            info["byte_length"],
            info["duration_seconds"],
            info["sample_rate"],
            info["channels"],
            info["bits_per_sample"],
            self.model_size,
            self._model is not None,
        )
        duration = info.get("duration_seconds")
        if duration is not None and duration > self.max_audio_duration_seconds:
            raise ValueError(
                "Audio buffer is too long for local STT: "
                f"{duration:.2f}s exceeds {self.max_audio_duration_seconds:.2f}s. "
                "Reduce receive timeout or split audio before transcription."
            )
        acquisition_started = time.perf_counter()
        model = self._get_model()
        acquired = time.perf_counter()
        # Use the same decoder as Whisper so resampling and channel conversion remain identical.
        from faster_whisper.audio import decode_audio
        audio = decode_audio(io.BytesIO(audio_bytes))
        decoded = time.perf_counter()
        segments, _ = model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
        )
        invoked = time.perf_counter()
        text = " ".join(seg.text.strip() for seg in segments).strip()
        finished = time.perf_counter()
        self.last_transcription_timing = {
            "input": info,
            "model_acquisition_ms": (acquired - acquisition_started) * 1000,
            "preprocessing_ms": (decoded - acquired) * 1000,
            "invocation_ms": (invoked - decoded) * 1000,
            "segment_materialization_ms": (finished - invoked) * 1000,
            "total_ms": (finished - started) * 1000,
            "rtf": (finished - started) / duration if duration else None,
            "language_hint": self.language,
            "cpu_threads": self.cpu_threads,
        }
        return text


# ===========================================================================
# Abstract TTS provider
# ===========================================================================

class TextToSpeechProvider(ABC):
    """
    Abstract Text-to-Speech provider interface.

    Concrete implementations:
      PiperTTS           — local, free (piper-tts library / binary)
      ElevenLabsTTS      — cloud, paid (future)
      AzureTTS           — cloud, paid (future)
      GoogleTTS          — cloud, paid (future)
      ClientTTS          — pass-through to client's own TTS (future)
    """

    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        """
        Convert text to audio.

        Parameters
        ----------
        text:
            The text string to synthesize.

        Returns
        -------
        bytes
            Raw WAV audio bytes.
        """
        ...

    def synthesize_to_file(self, text: str, output_path: str) -> str:
        """
        Synthesize text and write it to a WAV file.

        Returns the path of the written file.
        """
        audio_bytes = self.synthesize(text)
        Path(output_path).write_bytes(audio_bytes)
        return output_path


# ===========================================================================
# Concrete TTS: PiperTTS
# ===========================================================================

_PIPER_MODEL_CACHE: dict[str, Any] = {}
_PIPER_MODEL_CACHE_LOCK = threading.Lock()


class PiperTTS(TextToSpeechProvider):
    """
    TTS provider backed by Piper (local, free, neural voices).

    Piper can be used via:
      a) The 'piper' Python package  (pip install piper-tts)
      b) The standalone piper binary (subprocess call)

    This implementation tries (a) first and falls back to (b).

    Install option (a):
        pip install piper-tts

    Install option (b):
        Download piper binary from https://github.com/rhasspy/piper/releases
        and place it on your PATH.

    Voice model files (*.onnx + *.onnx.json) must be downloaded separately.
    See: https://huggingface.co/rhasspy/piper-voices

    The class lazily imports / locates piper on first synthesize() call.
    """

    def __init__(
        self,
        voice: str = "en_US-lessac-medium",
        model_path: Optional[str] = None,
        piper_binary: str = "piper",
        sample_rate: int = 22_050,
    ):
        self.voice = voice
        self.model_path = model_path or os.environ.get("PIPER_MODEL_PATH")
        self.piper_binary = piper_binary
        self.sample_rate = sample_rate
        self._piper_model = None  # lazy-loaded

    def _get_model(self):
        """Try to load the piper Python package model."""
        if self._piper_model is not None:
            return self._piper_model
        try:
            from piper.voice import PiperVoice  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "PiperTTS requires 'piper-tts' to be installed. "
                "Run: pip install piper-tts  "
                "or provide the piper binary path via piper_binary= constructor arg."
            ) from exc
        if self.model_path is None or not os.path.exists(self.model_path):
            raise ValueError(
                f"PiperTTS: model_path '{self.model_path}' not found. "
                "Set PIPER_MODEL_PATH env var or pass model_path directly. "
                "Please download a voice model (e.g. en_US-lessac-medium.onnx and .json) "
                "from https://huggingface.co/rhasspy/piper-voices and place it in the models/ directory."
            )
        cache_key = os.path.abspath(self.model_path)
        with _PIPER_MODEL_CACHE_LOCK:
            self._piper_model = _PIPER_MODEL_CACHE.get(cache_key)
            if self._piper_model is None:
                self._piper_model = PiperVoice.load(self.model_path)
                _PIPER_MODEL_CACHE[cache_key] = self._piper_model
        return self._piper_model

    def synthesize(self, text: str) -> bytes:
        """
        Synthesize text to WAV bytes using Piper.

        Tries the Python API first; falls back to subprocess (binary) if the
        Python package is unavailable.
        """
        try:
            return self._synthesize_python_api(text)
        except ImportError:
            return self._synthesize_binary(text)

    def _synthesize_python_api(self, text: str) -> bytes:
        model = self._get_model()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            model.synthesize_wav(text, wf)
        return buf.getvalue()

    def _synthesize_binary(self, text: str) -> bytes:
        """
        Fallback: call the piper binary via subprocess.

        Requires piper binary on PATH and a model path.
        """
        import subprocess
        import tempfile

        if self.model_path is None:
            raise ValueError(
                "PiperTTS binary mode requires model_path to be set."
            )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            proc = subprocess.run(
                [
                    self.piper_binary,
                    "--model", self.model_path,
                    "--output_file", tmp_path,
                ],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Piper binary failed (exit {proc.returncode}): "
                    f"{proc.stderr.decode(errors='replace')}"
                )
            return Path(tmp_path).read_bytes()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


# ===========================================================================
# LocalVoiceAdapter capabilities
# ===========================================================================

class LocalVoiceAdapterCapabilities(VoiceAdapterCapabilities):
    supports_audio_recording: bool = True
    supports_latency_measurement: bool = True
    supports_interruption_detection: bool = False
    supports_tool_calls: bool = False
    supports_handoff_detection: bool = False
    supports_real_time_streaming: bool = False
    supports_telephony: bool = False


# ===========================================================================
# LocalVoiceAdapter
# ===========================================================================

class LocalVoiceAdapter(VoiceAdapter):
    """
    Voice adapter for local development using free open-source tools.

    Architecture:
        Simulated user text
          -> PiperTTS (text -> WAV)
          -> WAV stored as artifact
          -> sent to voice agent endpoint (HTTP)
          -> agent audio response received
          -> FasterWhisperSTT (WAV -> text)
          -> VoiceTurn recorded
          -> VoiceConversation built

    This adapter is designed to talk to a locally running voice agent that
    accepts audio via HTTP POST and returns audio in its response body.
    The agent endpoint URL is configured via the 'agent_url' config key.

    Config keys:
      agent_url      str   HTTP endpoint of the voice agent under test
                           (must accept multipart/form-data with 'audio' field)
      audio_dir      str   Base directory for WAV artifacts
                           (default: "artifacts/voice")
      stt            dict  STT provider config:
                             provider: faster_whisper
                             model: small
                             device: cpu
                             compute_type: int8
      tts            dict  TTS provider config:
                             provider: piper
                             voice: en_US-lessac-medium
                             model_path: /path/to/model.onnx
      sample_rate    int   Audio sample rate (default: 16000)
      timeout        int   HTTP timeout seconds (default: 30)
    """

    def __init__(
        self,
        config: Optional[dict[str, Any]] = None,
        stt_provider: Optional[SpeechToTextProvider] = None,
        tts_provider: Optional[TextToSpeechProvider] = None,
    ):
        self.config = config or {}
        self._agent_url: Optional[str] = self.config.get("agent_url")
        self._audio_dir = Path(self.config.get("audio_dir", "artifacts/voice"))
        self._sample_rate: int = int(self.config.get("sample_rate", _DEFAULT_SAMPLE_RATE))
        self._timeout: int = int(self.config.get("timeout", 30))

        # STT provider — build from config if not explicitly injected
        if stt_provider is not None:
            self._stt = stt_provider
        else:
            stt_cfg = self.config.get("stt", {})
            provider_name = stt_cfg.get("provider", "faster_whisper")
            if provider_name == "faster_whisper":
                self._stt: SpeechToTextProvider = FasterWhisperSTT(
                    model_size=stt_cfg.get("model", "small"),
                    device=stt_cfg.get("device", "cpu"),
                    compute_type=stt_cfg.get("compute_type", "int8"),
                    language=stt_cfg.get("language"),
                )
            else:
                raise ValueError(f"Unknown STT provider: {provider_name!r}. "
                                 "Supported: faster_whisper")

        # TTS provider — build from config if not explicitly injected
        if tts_provider is not None:
            self._tts = tts_provider
        else:
            tts_cfg = self.config.get("tts", {})
            provider_name = tts_cfg.get("provider", "piper")
            if provider_name == "piper":
                self._tts: TextToSpeechProvider = PiperTTS(
                    voice=tts_cfg.get("voice", "en_US-lessac-medium"),
                    model_path=tts_cfg.get("model_path"),
                )
            else:
                raise ValueError(f"Unknown TTS provider: {provider_name!r}. "
                                 "Supported: piper")

        # Internal state
        self._session: Optional[VoiceSession] = None
        self._session_dir: Optional[Path] = None
        self._turns: list[VoiceTurn] = []
        self._events: list[VoiceEvent] = []
        self._tool_calls: list[ToolCall] = []
        self._tool_results: list[ToolResult] = []
        self._handoff_events: list[HandoffEvent] = []
        self._turn_index: int = 0

    @property
    def capabilities(self) -> LocalVoiceAdapterCapabilities:
        return LocalVoiceAdapterCapabilities()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start_session(self, config: Optional[dict[str, Any]] = None) -> str:
        session_id = str(uuid.uuid4())
        self._session = VoiceSession(
            session_id=session_id,
            channel="voice",
            started_at=datetime.now(timezone.utc).isoformat(),
            status=SessionStatus.active,
        )
        self._session_dir = self._audio_dir / session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[LocalVoiceAdapter] Session started: {session_id}")
        self._record_event(VoiceEventType.call_started)
        return session_id

    def end_session(self) -> VoiceConversation:
        if self._session is None:
            raise RuntimeError("end_session() called before start_session()")
        self._session.ended_at = datetime.now(timezone.utc).isoformat()
        self._session.status = SessionStatus.completed
        self._record_event(VoiceEventType.call_ended)
        logger.info(f"[LocalVoiceAdapter] Session ended: {self._session.session_id}")
        return self.get_conversation()

    # ------------------------------------------------------------------
    # Audio I/O
    # ------------------------------------------------------------------

    def send_audio(self, audio_bytes: bytes, turn_index: int = 0) -> None:
        if self._session is None:
            raise RuntimeError("send_audio() called before start_session()")
        audio_path = self._save_audio(audio_bytes, "user", turn_index)
        try:
            text = self._stt.transcribe(audio_bytes, self._sample_rate)
        except Exception as exc:
            logger.warning(f"[LocalVoiceAdapter] STT failed: {exc}")
            text = "[STT failed]"
        self._record_event(VoiceEventType.speech_started)
        self._turns.append(VoiceTurn(
            speaker=Speaker.user,
            text=text,
            audio_path=str(audio_path),
        ))
        self._record_event(VoiceEventType.speech_ended)

    def receive_audio(self, timeout_seconds: float = 30.0) -> bytes:
        """
        Send the last user audio to the agent endpoint and receive its response.
        """
        if self._session is None:
            raise RuntimeError("receive_audio() called before start_session()")
        if not self._agent_url:
            raise RuntimeError(
                "LocalVoiceAdapter: 'agent_url' must be set in config to call "
                "receive_audio(). Use FakeVoiceAdapter for testing without a backend."
            )

        import requests

        # Get last user turn audio
        user_turns_with_audio = [t for t in self._turns if t.speaker == Speaker.user and t.audio_path]
        if not user_turns_with_audio:
            raise RuntimeError("No user audio to send to agent.")
        last_user_audio_path = user_turns_with_audio[-1].audio_path

        self._record_event(VoiceEventType.response_started)
        t_start = time.perf_counter()

        with open(last_user_audio_path, "rb") as f:
            response = requests.post(
                self._agent_url,
                files={"audio": ("user_audio.wav", f, "audio/wav")},
                timeout=timeout_seconds,
            )
        response.raise_for_status()
        agent_audio = response.content
        latency_ms = (time.perf_counter() - t_start) * 1000.0

        # STT on agent response
        try:
            agent_text = self._stt.transcribe(agent_audio, self._sample_rate)
        except Exception as exc:
            logger.warning(f"[LocalVoiceAdapter] Agent STT failed: {exc}")
            agent_text = "[agent STT failed]"

        audio_path = self._save_audio(agent_audio, "agent", self._turn_index)
        self._turns.append(VoiceTurn(
            speaker=Speaker.agent,
            text=agent_text,
            latency_ms=latency_ms,
            audio_path=str(audio_path),
        ))
        self._turn_index += 1
        self._record_event(VoiceEventType.response_completed)
        return agent_audio

    def send_text(self, text: str, turn_index: int = 0) -> None:
        """Convert text to audio via TTS, then call send_audio()."""
        if self._session is None:
            raise RuntimeError("send_text() called before start_session()")
        try:
            audio_bytes = self._tts.synthesize(text)
        except Exception as exc:
            logger.error(f"[LocalVoiceAdapter] TTS failed: {exc}")
            raise
        self.send_audio(audio_bytes, turn_index=turn_index)
        # Override the auto-transcribed text with the original TTS input
        user_turns = [t for t in self._turns if t.speaker == Speaker.user]
        if user_turns:
            user_turns[-1].text = text

    def receive_text(self, timeout_seconds: float = 30.0) -> str:
        """Receive agent audio and return transcribed text."""
        self.receive_audio(timeout_seconds=timeout_seconds)
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
        filename = f"{speaker}_{index:03d}.wav"
        path = self._session_dir / filename
        path.write_bytes(audio_bytes)
        return path
