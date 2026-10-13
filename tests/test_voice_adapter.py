"""
Tests for FakeVoiceAdapter, VoiceAdapter interface, STT/TTS provider interfaces,
audio artifact creation, and event recording.

All tests use only stdlib or already-installed packages.
No paid API keys, no real phone calls, no external services required.
"""

from __future__ import annotations

import io
import wave
import struct
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.adapters.voice.base import VoiceAdapter, VoiceAdapterCapabilities
from app.adapters.voice.fake import FakeVoiceAdapter, _make_wav_bytes, _SILENT_PCM, _SAMPLE_RATE
from app.adapters.voice.local import (
    SpeechToTextProvider,
    TextToSpeechProvider,
    FasterWhisperSTT,
    PiperTTS,
    LocalVoiceAdapter,
)
from app.models.voice import (
    SessionStatus,
    Speaker,
    VoiceConversation,
    VoiceEventType,
)
from app.voice.config import VoiceAdapterConfig, STTConfig, TTSConfig


# ===========================================================================
# Helpers
# ===========================================================================

def _silent_wav() -> bytes:
    """Generate a minimal silent WAV for testing."""
    return _make_wav_bytes(_SILENT_PCM, _SAMPLE_RATE)


# ===========================================================================
# 1. VoiceAdapter interface tests (using FakeVoiceAdapter as concrete subject)
# ===========================================================================

class TestVoiceAdapterInterface:
    def test_is_abstract(self):
        """VoiceAdapter cannot be instantiated directly."""
        with pytest.raises(TypeError):
            VoiceAdapter()

    def test_fake_is_voice_adapter(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        assert isinstance(adapter, VoiceAdapter)

    def test_default_capabilities(self):
        caps = VoiceAdapterCapabilities()
        assert caps.supports_latency_measurement is True
        assert caps.supports_audio_recording is False
        assert caps.supports_telephony is False

    def test_fake_capabilities(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        caps = adapter.capabilities
        assert caps.supports_audio_recording is True
        assert caps.supports_telephony is False


# ===========================================================================
# 2. FakeVoiceAdapter: session lifecycle
# ===========================================================================

class TestFakeVoiceAdapterSession:
    def test_start_session_returns_session_id(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        sid = adapter.start_session()
        assert isinstance(sid, str)
        assert len(sid) > 0

    def test_session_is_active_after_start(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        adapter.start_session()
        session = adapter.get_session()
        assert session is not None
        assert session.status == SessionStatus.active

    def test_session_dir_created(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        sid = adapter.start_session()
        session_dir = tmp_path / sid
        assert session_dir.exists()

    def test_end_session_returns_voice_conversation(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        adapter.start_session()
        vc = adapter.end_session()
        assert isinstance(vc, VoiceConversation)

    def test_end_session_marks_completed(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        adapter.start_session()
        vc = adapter.end_session()
        assert vc.session.status == SessionStatus.completed
        assert vc.session.ended_at is not None

    def test_end_session_without_start_raises(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        with pytest.raises(RuntimeError, match="before start_session"):
            adapter.end_session()


# ===========================================================================
# 3. FakeVoiceAdapter: audio artifact creation
# ===========================================================================

class TestFakeVoiceAdapterAudio:
    def test_send_audio_creates_wav_file(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        sid = adapter.start_session()
        wav = _silent_wav()
        adapter.send_audio(wav, turn_index=0)
        files = list((tmp_path / sid).glob("user_*.wav"))
        assert len(files) == 1

    def test_receive_audio_creates_agent_wav(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        sid = adapter.start_session()
        audio = adapter.receive_audio()
        assert isinstance(audio, bytes)
        files = list((tmp_path / sid).glob("agent_*.wav"))
        assert len(files) == 1

    def test_wav_file_is_valid(self, tmp_path):
        """The generated WAV file must be parseable by the stdlib wave module."""
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        sid = adapter.start_session()
        adapter.receive_audio()
        wav_file = list((tmp_path / sid).glob("agent_*.wav"))[0]
        with wave.open(str(wav_file), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2

    def test_multiple_turns_create_separate_files(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        sid = adapter.start_session()
        adapter.send_text("Hello", turn_index=0)
        adapter.receive_audio()
        adapter.send_text("And another", turn_index=1)
        adapter.receive_audio()
        user_files = list((tmp_path / sid).glob("user_*.wav"))
        agent_files = list((tmp_path / sid).glob("agent_*.wav"))
        assert len(user_files) == 2
        assert len(agent_files) == 2


    def test_configurable_audio_dir(self, tmp_path):
        custom_dir = tmp_path / "custom_audio"
        adapter = FakeVoiceAdapter(config={"audio_dir": str(custom_dir)})
        adapter.start_session()
        # session_dir should be inside custom_dir
        assert custom_dir.exists()


# ===========================================================================
# 4. FakeVoiceAdapter: conversation turns
# ===========================================================================

class TestFakeVoiceAdapterTurns:
    def test_send_text_records_user_turn(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        adapter.start_session()
        adapter.send_text("My order is damaged.")
        turns = adapter.get_transcript()
        user_turns = [t for t in turns if t.speaker == Speaker.user]
        assert len(user_turns) == 1
        assert user_turns[0].text == "My order is damaged."

    def test_receive_text_records_agent_turn(self, tmp_path):
        adapter = FakeVoiceAdapter(
            config={
                "audio_dir": str(tmp_path),
                "responses": ["Thank you for calling."],
            }
        )
        adapter.start_session()
        reply = adapter.receive_text()
        assert reply == "Thank you for calling."
        turns = adapter.get_transcript()
        agent_turns = [t for t in turns if t.speaker == Speaker.agent]
        assert len(agent_turns) == 1
        assert agent_turns[0].text == "Thank you for calling."

    def test_scripted_responses_cycle(self, tmp_path):
        adapter = FakeVoiceAdapter(
            config={
                "audio_dir": str(tmp_path),
                "responses": ["A", "B"],
                "latency_ms": 0,
            }
        )
        adapter.start_session()
        r1 = adapter.receive_text()
        r2 = adapter.receive_text()
        r3 = adapter.receive_text()  # wraps around
        assert r1 == "A"
        assert r2 == "B"
        assert r3 == "A"

    def test_agent_turn_has_latency(self, tmp_path):
        adapter = FakeVoiceAdapter(
            config={"audio_dir": str(tmp_path), "latency_ms": 200, "responses": ["Hi"]}
        )
        adapter.start_session()
        adapter.receive_audio()
        turns = adapter.get_transcript()
        agent_turns = [t for t in turns if t.speaker == Speaker.agent]
        assert agent_turns[0].latency_ms == 200.0

    def test_full_turn_sequence(self, tmp_path):
        adapter = FakeVoiceAdapter(
            config={
                "audio_dir": str(tmp_path),
                "responses": ["Hello!", "Goodbye!"],
                "latency_ms": 0,
            }
        )
        adapter.start_session()
        adapter.send_text("Hi", turn_index=0)
        reply1 = adapter.receive_text()
        adapter.send_text("Bye", turn_index=1)
        reply2 = adapter.receive_text()
        vc = adapter.end_session()

        assert reply1 == "Hello!"
        assert reply2 == "Goodbye!"
        assert len(vc.turns) == 4  # 2 user + 2 agent


# ===========================================================================
# 5. FakeVoiceAdapter: event recording
# ===========================================================================

class TestFakeVoiceAdapterEvents:
    def test_call_started_event_on_session_start(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        adapter.start_session()
        events = adapter.get_events()
        event_types = [e.event_type for e in events]
        assert VoiceEventType.call_started in event_types

    def test_call_ended_event_on_session_end(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        adapter.start_session()
        adapter.end_session()
        events = adapter.get_events()
        event_types = [e.event_type for e in events]
        assert VoiceEventType.call_ended in event_types

    def test_speech_events_on_send_text(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        adapter.start_session()
        adapter.send_text("Hello")
        events = adapter.get_events()
        event_types = [e.event_type for e in events]
        assert VoiceEventType.speech_started in event_types
        assert VoiceEventType.speech_ended in event_types

    def test_response_events_on_receive(self, tmp_path):
        adapter = FakeVoiceAdapter(config={"audio_dir": str(tmp_path)})
        adapter.start_session()
        adapter.receive_audio()
        events = adapter.get_events()
        event_types = [e.event_type for e in events]
        assert VoiceEventType.response_started in event_types
        assert VoiceEventType.response_completed in event_types

    def test_get_conversation_assembles_full_record(self, tmp_path):
        adapter = FakeVoiceAdapter(
            config={
                "audio_dir": str(tmp_path),
                "responses": ["Got it."],
                "latency_ms": 0,
            }
        )
        adapter.start_session()
        adapter.send_text("Help!")
        adapter.receive_text()
        vc = adapter.get_conversation()
        assert isinstance(vc, VoiceConversation)
        assert vc.session.session_id is not None
        assert len(vc.turns) == 2
        assert len(vc.events) > 0


# ===========================================================================
# 6. STT / TTS provider interface tests
# ===========================================================================

class TestSTTProviderInterface:
    def test_speech_to_text_is_abstract(self):
        with pytest.raises(TypeError):
            SpeechToTextProvider()

    def test_custom_stt_provider_works(self):
        """A custom STT subclass can be injected without modifying adapters."""
        class EchoSTT(SpeechToTextProvider):
            def transcribe(self, audio_bytes: bytes, sample_rate: int = 16_000) -> str:
                return "custom transcription"

        stt = EchoSTT()
        result = stt.transcribe(b"fake audio")
        assert result == "custom transcription"

    def test_transcribe_file_calls_transcribe(self, tmp_path):
        class EchoSTT(SpeechToTextProvider):
            def transcribe(self, audio_bytes: bytes, sample_rate: int = 16_000) -> str:
                return f"bytes:{len(audio_bytes)}"

        wav_path = tmp_path / "test.wav"
        wav_path.write_bytes(b"RIFF...fake")
        stt = EchoSTT()
        result = stt.transcribe_file(str(wav_path))
        assert "bytes:11" in result

    def test_faster_whisper_stt_defers_import(self):
        """FasterWhisperSTT can be constructed without faster-whisper installed."""
        stt = FasterWhisperSTT(model_size="tiny")
        assert stt.model_size == "tiny"
        assert stt._model is None  # not loaded yet

    def test_faster_whisper_stt_raises_import_error_on_transcribe(self):
        """If faster-whisper is not installed, transcribe() raises ImportError."""
        stt = FasterWhisperSTT()
        with patch.dict("sys.modules", {"faster_whisper": None}):
            stt._model = None  # force re-import attempt
            with pytest.raises((ImportError, ModuleNotFoundError)):
                stt._get_model()

    def test_faster_whisper_stt_rejects_overlong_audio_before_model_load(self):
        stt = FasterWhisperSTT(model_size="tiny", max_audio_duration_seconds=0.05)

        with pytest.raises(ValueError, match="Audio buffer is too long"):
            stt.transcribe(_silent_wav())

        assert stt._model is None


class TestTTSProviderInterface:
    def test_text_to_speech_is_abstract(self):
        with pytest.raises(TypeError):
            TextToSpeechProvider()

    def test_custom_tts_provider_works(self):
        """A custom TTS subclass can be injected without modifying adapters."""
        class SilentTTS(TextToSpeechProvider):
            def synthesize(self, text: str) -> bytes:
                return _make_wav_bytes(_SILENT_PCM)

        tts = SilentTTS()
        wav = tts.synthesize("Hello world")
        assert wav[:4] == b"RIFF"  # valid WAV header

    def test_synthesize_to_file(self, tmp_path):
        class SilentTTS(TextToSpeechProvider):
            def synthesize(self, text: str) -> bytes:
                return _make_wav_bytes(_SILENT_PCM)

        out_path = str(tmp_path / "out.wav")
        tts = SilentTTS()
        result = tts.synthesize_to_file("Hello", out_path)
        assert result == out_path
        assert Path(out_path).exists()

    def test_piper_tts_defers_import(self):
        """PiperTTS can be constructed without piper installed."""
        tts = PiperTTS(voice="en_US-lessac-medium")
        assert tts.voice == "en_US-lessac-medium"
        assert tts._piper_model is None

    def test_piper_tts_raises_import_error_on_synthesize(self):
        """If piper is not installed, synthesize() raises ImportError."""
        tts = PiperTTS(model_path="/fake/model.onnx")
        with patch.dict("sys.modules", {"piper": None, "piper.voice": None}):
            tts._piper_model = None
            with pytest.raises((ImportError, ModuleNotFoundError, Exception)):
                tts._synthesize_python_api("test")

    @patch.dict(os.environ, clear=True)
    def test_piper_tts_missing_model_path_raises_error(self):
        """If no model_path is provided and PIPER_MODEL_PATH is unset, raise ValueError."""
        # Ensure we don't have PIPER_MODEL_PATH set
        if "PIPER_MODEL_PATH" in os.environ:
            del os.environ["PIPER_MODEL_PATH"]
            
        tts = PiperTTS(model_path=None)
        with pytest.raises(ValueError, match="not found|Set PIPER_MODEL_PATH"):
            tts._get_model()

    def test_piper_tts_synthesize_produces_audio(self):
        """Verify PiperTTS synthesize() returns valid non-empty WAV bytes if model exists."""
        model_path = "models/en_US-lessac-medium.onnx"
        if not os.path.exists(model_path):
            pytest.skip(f"Piper model not found at {model_path}")
            
        tts = PiperTTS(model_path=model_path)
        wav_bytes = tts.synthesize("Hello world.")
        
        assert isinstance(wav_bytes, bytes)
        assert wav_bytes.startswith(b"RIFF")
        assert b"WAVE" in wav_bytes[:12]
        assert len(wav_bytes) > 44  # Header is 44 bytes, so it must have audio payload


# ===========================================================================
# 7. LocalVoiceAdapter: injection-based testing (no real TTS/STT needed)
# ===========================================================================

class TestLocalVoiceAdapterWithMocks:
    def _make_mock_stt(self, return_text="transcribed text"):
        stt = MagicMock(spec=SpeechToTextProvider)
        stt.transcribe.return_value = return_text
        return stt

    def _make_mock_tts(self):
        tts = MagicMock(spec=TextToSpeechProvider)
        tts.synthesize.return_value = _make_wav_bytes(_SILENT_PCM)
        return tts

    def test_local_adapter_can_be_constructed_with_injected_providers(self, tmp_path):
        stt = self._make_mock_stt()
        tts = self._make_mock_tts()
        adapter = LocalVoiceAdapter(
            config={"audio_dir": str(tmp_path)},
            stt_provider=stt,
            tts_provider=tts,
        )
        assert isinstance(adapter, VoiceAdapter)

    def test_local_adapter_send_text_calls_tts_then_stt(self, tmp_path):
        stt = self._make_mock_stt("hello from user")
        tts = self._make_mock_tts()
        adapter = LocalVoiceAdapter(
            config={"audio_dir": str(tmp_path)},
            stt_provider=stt,
            tts_provider=tts,
        )
        adapter.start_session()
        adapter.send_text("My order is damaged")
        tts.synthesize.assert_called_once_with("My order is damaged")
        # STT was called on the audio produced by TTS
        stt.transcribe.assert_called()
        # User turn has the original TTS text (not STT output)
        turns = adapter.get_transcript()
        user_turns = [t for t in turns if t.speaker == Speaker.user]
        assert user_turns[0].text == "My order is damaged"

    def test_local_adapter_creates_audio_artifact(self, tmp_path):
        stt = self._make_mock_stt()
        tts = self._make_mock_tts()
        adapter = LocalVoiceAdapter(
            config={"audio_dir": str(tmp_path)},
            stt_provider=stt,
            tts_provider=tts,
        )
        sid = adapter.start_session()
        adapter.send_text("Test")
        files = list((tmp_path / sid).glob("user_*.wav"))
        assert len(files) == 1

    def test_local_adapter_end_session_returns_conversation(self, tmp_path):
        stt = self._make_mock_stt()
        tts = self._make_mock_tts()
        adapter = LocalVoiceAdapter(
            config={"audio_dir": str(tmp_path)},
            stt_provider=stt,
            tts_provider=tts,
        )
        adapter.start_session()
        vc = adapter.end_session()
        assert isinstance(vc, VoiceConversation)
        assert vc.session.status == SessionStatus.completed


# ===========================================================================
# 8. Voice configuration model tests
# ===========================================================================

class TestVoiceAdapterConfig:
    def test_defaults(self):
        cfg = VoiceAdapterConfig()
        assert cfg.type == "fake"
        assert cfg.audio.sample_rate == 16_000
        assert cfg.speech.stt.provider == "faster_whisper"
        assert cfg.speech.tts.provider == "piper"
        assert cfg.session.max_turns == 10

    def test_to_adapter_config_dict(self):
        cfg = VoiceAdapterConfig(audio_dir="artifacts/test_voice")
        d = cfg.to_adapter_config_dict()
        assert d["audio_dir"] == "artifacts/test_voice"
        assert "stt" in d
        assert "tts" in d
        assert d["stt"]["provider"] == "faster_whisper"

    def test_custom_stt_config(self):
        cfg = VoiceAdapterConfig(speech={"stt": {"provider": "faster_whisper", "model": "large"}})
        assert cfg.speech.stt.model == "large"

    def test_custom_session_config(self):
        cfg = VoiceAdapterConfig(session={"max_turns": 5})
        assert cfg.session.max_turns == 5
