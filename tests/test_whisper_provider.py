from __future__ import annotations

import pytest

from app.calling.audio_metadata import AudioMetadata
from app.calling.providers.whisper import WhisperTranscriptionProvider
from app.calling.whisper_config import WhisperTranscriptionConfig
from app.calling.whisper_models import (
    WhisperAPIError,
    WhisperEmptyTranscriptError,
    WhisperInvalidAudioError,
    WhisperTimeoutError,
)


class FakeTranscriptions:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeAudio:
    def __init__(self, response=None, error=None):
        self.transcriptions = FakeTranscriptions(response=response, error=error)


class FakeClient:
    def __init__(self, response=None, error=None):
        self.audio = FakeAudio(response=response, error=error)


def test_whisper_provider_initializes_with_config():
    config = WhisperTranscriptionConfig(
        api_key="secret-key",
        model="whisper-1",
        language="en",
        temperature=0.2,
        prompt="Customer support call",
        timeout_seconds=12,
        supported_formats=("wav", "mp3"),
        default_speaker_label="customer",
    )

    provider = WhisperTranscriptionProvider(config=config, client=FakeClient())

    assert provider.provider_name == "openai_whisper"
    assert provider.config.model == "whisper-1"
    assert provider.config.supported_formats == ("wav", "mp3")
    assert provider.config.default_speaker_label == "customer"


def test_whisper_config_rejects_invalid_values():
    with pytest.raises(ValueError):
        WhisperTranscriptionConfig(model=" ")
    with pytest.raises(ValueError):
        WhisperTranscriptionConfig(temperature=-1)
    with pytest.raises(ValueError):
        WhisperTranscriptionConfig(timeout_seconds=0)
    with pytest.raises(ValueError):
        WhisperTranscriptionConfig(supported_formats=())
    with pytest.raises(ValueError):
        WhisperTranscriptionConfig(default_speaker_label=" ")


def test_whisper_provider_generates_raw_transcript_from_segments(tmp_path):
    audio_path = tmp_path / "call.wav"
    audio_path.write_bytes(b"fake-audio")
    response = {
        "segments": [
            {"text": "Hello", "start": 0.0, "end": 1.2, "confidence": 0.95},
            {"text": "How can I help?", "start": 1.3, "end": 3.0, "confidence": 0.9},
        ]
    }
    client = FakeClient(response=response)
    metadata = AudioMetadata(duration_seconds=3.0, codec="wav", channels=1)
    provider = WhisperTranscriptionProvider(client=client)

    result = provider.transcribe(
        audio_uri=str(audio_path),
        audio_metadata=metadata,
        metadata={"call_sid": "CA123"},
    )

    assert result.source == "stt"
    assert result.provider_name == "openai_whisper"
    assert result.audio_metadata == metadata
    assert result.metadata["call_sid"] == "CA123"
    assert [segment.speaker for segment in result.segments] == ["speaker_0", "speaker_0"]
    assert [segment.text for segment in result.segments] == ["Hello", "How can I help?"]
    assert client.audio.transcriptions.calls[0]["response_format"] == "verbose_json"


def test_whisper_provider_generates_raw_transcript_from_plain_text(tmp_path):
    audio_path = tmp_path / "call.mp3"
    audio_path.write_bytes(b"fake-audio")
    provider = WhisperTranscriptionProvider(client=FakeClient(response={"text": "Hello there"}))

    result = provider.transcribe(audio_uri=str(audio_path))

    assert len(result.segments) == 1
    assert result.segments[0].speaker == "speaker_0"
    assert result.segments[0].text == "Hello there"


def test_whisper_provider_rejects_invalid_audio(tmp_path):
    provider = WhisperTranscriptionProvider(client=FakeClient())

    with pytest.raises(WhisperInvalidAudioError):
        provider.transcribe(audio_uri=str(tmp_path / "missing.wav"))

    bad_audio = tmp_path / "call.flac"
    bad_audio.write_bytes(b"fake-audio")
    with pytest.raises(WhisperInvalidAudioError):
        provider.transcribe(audio_uri=str(bad_audio))


def test_whisper_provider_handles_empty_transcript(tmp_path):
    audio_path = tmp_path / "call.ogg"
    audio_path.write_bytes(b"fake-audio")
    provider = WhisperTranscriptionProvider(client=FakeClient(response={"segments": []}))

    with pytest.raises(WhisperEmptyTranscriptError):
        provider.transcribe(audio_uri=str(audio_path))


def test_whisper_provider_handles_timeout_and_api_failures(tmp_path):
    audio_path = tmp_path / "call.m4a"
    audio_path.write_bytes(b"fake-audio")

    timeout_provider = WhisperTranscriptionProvider(client=FakeClient(error=TimeoutError()))
    with pytest.raises(WhisperTimeoutError):
        timeout_provider.transcribe(audio_uri=str(audio_path))

    api_provider = WhisperTranscriptionProvider(client=FakeClient(error=RuntimeError("boom")))
    with pytest.raises(WhisperAPIError):
        api_provider.transcribe(audio_uri=str(audio_path))


def test_whisper_provider_handles_rate_limit(tmp_path):
    class RateLimitError(Exception):
        status_code = 429

    audio_path = tmp_path / "call.wav"
    audio_path.write_bytes(b"fake-audio")
    provider = WhisperTranscriptionProvider(client=FakeClient(error=RateLimitError()))

    with pytest.raises(WhisperAPIError, match="rate limited"):
        provider.transcribe(audio_uri=str(audio_path))
