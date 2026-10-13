from __future__ import annotations

import pytest

from app.calling.audio_metadata import AudioMetadata
from app.calling.transcription import RawTranscript, RawTranscriptSegment
from app.calling.transcription_provider import ManualTranscriptionProvider, TranscriptionProvider
from app.calling.transcription_registry import (
    DuplicateTranscriptionProviderError,
    TranscriptionProviderRegistry,
    UnknownTranscriptionProviderError,
)


def test_transcription_provider_is_abstract():
    with pytest.raises(TypeError):
        TranscriptionProvider()


def test_manual_transcription_provider_returns_supplied_transcript_with_audio_metadata():
    raw = RawTranscript(
        source="manual",
        segments=[RawTranscriptSegment(speaker="customer", text="Hello")],
    )
    metadata = AudioMetadata(duration_seconds=4.2, codec="wav", channels=1)
    provider = ManualTranscriptionProvider(raw)

    result = provider.transcribe(audio_uri="memory://audio.wav", audio_metadata=metadata)

    assert result.source == "manual"
    assert result.audio_metadata == metadata
    assert result.segments[0].text == "Hello"


def test_transcription_registry_registers_and_lists_provider():
    registry = TranscriptionProviderRegistry()
    provider = ManualTranscriptionProvider(RawTranscript(source="manual"))

    registry.register(provider)

    assert registry.get("manual") is provider
    assert registry.list() == ["manual"]


def test_transcription_registry_rejects_duplicate_and_unknown():
    registry = TranscriptionProviderRegistry()
    provider = ManualTranscriptionProvider(RawTranscript(source="manual"))
    registry.register(provider)

    with pytest.raises(DuplicateTranscriptionProviderError):
        registry.register(provider)
    with pytest.raises(UnknownTranscriptionProviderError):
        registry.get("missing")


def test_audio_metadata_serializes_provider_metadata():
    metadata = AudioMetadata(
        duration_seconds=5.0,
        codec="pcm",
        sample_rate_hz=16000,
        channels=2,
        bitrate_bps=256000,
        file_size_bytes=1024,
        provider_metadata={"recording_sid": "RE123"},
    )

    data = metadata.model_dump(mode="json")

    assert data["duration_seconds"] == 5.0
    assert data["provider_metadata"] == {"recording_sid": "RE123"}
