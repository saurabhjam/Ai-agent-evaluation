"""
Voice channel configuration models.

These Pydantic models represent the structure of the 'agent' block in a
voice scenario YAML file:

    channel: voice
    adapter:
      type: fake          # or: local, websocket, twilio, vapi, etc.

    speech:
      stt:
        provider: faster_whisper
        model: small
        device: cpu
      tts:
        provider: piper
        voice: en_US-lessac-medium
        model_path: /path/to/model.onnx

    audio:
      sample_rate: 16000
      format: wav

    session:
      max_turns: 10
      timeout_seconds: 30

    audio_dir: artifacts/voice

These are parsed by VoiceAdapterFactory.create_from_config() and passed
to the appropriate VoiceAdapter implementation.

Nothing here is vendor-specific.  Vendor adapters declare their own
additional config fields if needed.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class STTConfig(BaseModel):
    """Speech-to-Text provider configuration."""
    provider: str = "faster_whisper"
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    language: Optional[str] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class TTSConfig(BaseModel):
    """Text-to-Speech provider configuration."""
    model_config = {"protected_namespaces": ()}  # suppress 'model_path' namespace warning
    provider: str = "piper"
    voice: str = "en_US-lessac-medium"
    model_path: Optional[str] = None
    piper_binary: str = "piper"
    sample_rate: int = 22_050
    extra: dict[str, Any] = Field(default_factory=dict)



class SpeechConfig(BaseModel):
    """Combined speech pipeline configuration."""
    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)


class AudioConfig(BaseModel):
    """Audio I/O configuration."""
    sample_rate: int = 16_000
    format: str = "wav"
    channels: int = 1
    sample_width: int = 2      # bytes (16-bit)


class SessionConfig(BaseModel):
    """Voice session configuration."""
    max_turns: int = 10
    timeout_seconds: float = 30.0


class LatencyMetricConfig(BaseModel):
    enabled: bool = True
    warning_ms: float = 1500.0
    failure_ms: float = 5000.0


class TurnTakingMetricConfig(BaseModel):
    enabled: bool = True


class InterruptionMetricConfig(BaseModel):
    enabled: bool = True
    max_allowed: int = 0


class SilenceMetricConfig(BaseModel):
    enabled: bool = True
    max_gap_ms: float = 5000.0


class AudioEvidenceMetricConfig(BaseModel):
    enabled: bool = True


class SessionCompletionMetricConfig(BaseModel):
    enabled: bool = True


class VoiceMetricsConfig(BaseModel):
    """Configuration for all voice-specific deterministic metrics."""
    latency: LatencyMetricConfig = Field(default_factory=LatencyMetricConfig)
    turn_taking: TurnTakingMetricConfig = Field(default_factory=TurnTakingMetricConfig)
    interruption: InterruptionMetricConfig = Field(default_factory=InterruptionMetricConfig)
    silence: SilenceMetricConfig = Field(default_factory=SilenceMetricConfig)
    audio: AudioEvidenceMetricConfig = Field(default_factory=AudioEvidenceMetricConfig)
    session_completion: SessionCompletionMetricConfig = Field(default_factory=SessionCompletionMetricConfig)


class VoiceAdapterConfig(BaseModel):
    """
    Top-level voice adapter configuration parsed from the scenario YAML.

    Example YAML block (under 'agent'):

        channel: voice
        adapter:
          type: fake
        speech:
          stt:
            provider: faster_whisper
            model: small
          tts:
            provider: piper
            voice: en_US-lessac-medium
        audio:
          sample_rate: 16000
        session:
          max_turns: 10
        audio_dir: artifacts/voice
    """
    type: str = "fake"          # fake | local | websocket | (future: vapi | twilio)
    speech: SpeechConfig = Field(default_factory=SpeechConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    audio_dir: str = "artifacts/voice"
    agent_url: Optional[str] = None
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_adapter_config_dict(self) -> dict[str, Any]:
        """
        Flatten this model into the dict format consumed by VoiceAdapter constructors.
        """
        return {
            "audio_dir": self.audio_dir,
            "sample_rate": self.audio.sample_rate,
            "agent_url": self.agent_url,
            "stt": {
                "provider": self.speech.stt.provider,
                "model": self.speech.stt.model,
                "device": self.speech.stt.device,
                "compute_type": self.speech.stt.compute_type,
                "language": self.speech.stt.language,
                **self.speech.stt.extra,
            },
            "tts": {
                "provider": self.speech.tts.provider,
                "voice": self.speech.tts.voice,
                "model_path": self.speech.tts.model_path,
                "piper_binary": self.speech.tts.piper_binary,
                **self.speech.tts.extra,
            },
            **self.extra,
        }
