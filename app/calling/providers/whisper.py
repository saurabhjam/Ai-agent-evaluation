"""OpenAI Whisper transcription provider."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from app.calling.audio_metadata import AudioMetadata
from app.calling.transcription import RawTranscript, RawTranscriptSegment
from app.calling.transcription_provider import TranscriptionProvider
from app.calling.whisper_config import WhisperTranscriptionConfig
from app.calling.whisper_models import (
    WhisperAPIError,
    WhisperEmptyTranscriptError,
    WhisperInvalidAudioError,
    WhisperResponseFormat,
    WhisperTimeoutError,
)


class WhisperTranscriptionProvider(TranscriptionProvider):
    """OpenAI Whisper implementation of the calling transcription interface."""

    provider_name = "openai_whisper"

    def __init__(
        self,
        config: Optional[WhisperTranscriptionConfig] = None,
        *,
        client: Optional[Any] = None,
    ):
        self.config = config or WhisperTranscriptionConfig()
        self._client = client

    def transcribe(
        self,
        *,
        audio_uri: str,
        audio_metadata: Optional[AudioMetadata] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> RawTranscript:
        """Transcribe a local audio file into a provider-neutral raw transcript."""
        audio_path = self._validate_audio_uri(audio_uri)
        client = self._client or self._create_client()

        try:
            with audio_path.open("rb") as audio_file:
                response = client.audio.transcriptions.create(
                    file=audio_file,
                    model=self.config.model,
                    language=self.config.language,
                    temperature=self.config.temperature,
                    prompt=self.config.prompt,
                    response_format=WhisperResponseFormat.verbose_json.value,
                    timeout=self.config.timeout_seconds,
                )
        except TimeoutError as exc:
            raise WhisperTimeoutError("Whisper transcription timed out") from exc
        except Exception as exc:
            if self._is_rate_limit_error(exc):
                raise WhisperAPIError("Whisper transcription was rate limited") from exc
            raise WhisperAPIError("Whisper transcription failed") from exc

        segments = self._segments_from_response(response)
        if not segments:
            raise WhisperEmptyTranscriptError("Whisper returned an empty transcript")

        merged_metadata = {
            "audio_uri": str(audio_path),
            "model": self.config.model,
            "language": self.config.language,
            "response_format": WhisperResponseFormat.verbose_json.value,
        }
        if metadata:
            merged_metadata.update(metadata)

        return RawTranscript(
            source="stt",
            provider_name=self.provider_name,
            segments=segments,
            audio_metadata=audio_metadata,
            metadata=merged_metadata,
        )

    def _validate_audio_uri(self, audio_uri: str) -> Path:
        if not audio_uri or not audio_uri.strip():
            raise WhisperInvalidAudioError("Audio URI is required")

        audio_path = Path(audio_uri).expanduser()
        if not audio_path.exists() or not audio_path.is_file():
            raise WhisperInvalidAudioError("Audio file does not exist")

        extension = audio_path.suffix.lower().lstrip(".")
        if extension not in self.config.supported_formats:
            raise WhisperInvalidAudioError("Audio format is not supported by this provider")

        return audio_path

    def _create_client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise WhisperAPIError("OpenAI SDK is required for Whisper transcription") from exc

        api_key = self.config.api_key.get_secret_value() if self.config.api_key else None
        return OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))

    def _segments_from_response(self, response: Any) -> list[RawTranscriptSegment]:
        raw_segments = self._get_value(response, "segments") or []
        segments: list[RawTranscriptSegment] = []

        for index, raw_segment in enumerate(raw_segments):
            text = (self._get_value(raw_segment, "text") or "").strip()
            if not text:
                continue
            segments.append(
                RawTranscriptSegment(
                    speaker=self.config.default_speaker_label,
                    text=text,
                    start_time=self._get_value(raw_segment, "start"),
                    end_time=self._get_value(raw_segment, "end"),
                    confidence=self._get_value(raw_segment, "confidence"),
                    metadata={
                        "whisper_segment_index": index,
                        "whisper_segment": self._safe_metadata(raw_segment),
                    },
                )
            )

        if segments:
            return segments

        text = (self._get_value(response, "text") or "").strip()
        if not text:
            return []
        return [RawTranscriptSegment(speaker=self.config.default_speaker_label, text=text)]

    def _get_value(self, source: Any, key: str) -> Any:
        if isinstance(source, dict):
            return source.get(key)
        return getattr(source, key, None)

    def _safe_metadata(self, source: Any) -> dict[str, Any]:
        if isinstance(source, dict):
            return {key: value for key, value in source.items() if key != "text"}
        if hasattr(source, "model_dump"):
            return {key: value for key, value in source.model_dump().items() if key != "text"}
        return {}

    def _is_rate_limit_error(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        return status_code == 429 or exc.__class__.__name__ == "RateLimitError"
