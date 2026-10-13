"""Speaker normalization for calling transcripts."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.calling.models import TranscriptSpeaker


class UnknownSpeakerError(ValueError):
    """Raised when a transcript speaker cannot be normalized."""


DEFAULT_SPEAKER_MAP = {
    "speaker_0": TranscriptSpeaker.customer,
    "channel_0": TranscriptSpeaker.customer,
    "customer": TranscriptSpeaker.customer,
    "caller": TranscriptSpeaker.customer,
    "user": TranscriptSpeaker.customer,
    "simulated_user": TranscriptSpeaker.customer,
    "speaker_1": TranscriptSpeaker.agent,
    "channel_1": TranscriptSpeaker.agent,
    "assistant": TranscriptSpeaker.agent,
    "agent": TranscriptSpeaker.agent,
    "callee": TranscriptSpeaker.agent,
    "ai": TranscriptSpeaker.agent,
}


@dataclass(frozen=True)
class SpeakerMapper:
    """Maps provider speaker labels to calling transcript speakers."""

    speaker_map: dict[str, TranscriptSpeaker] = field(default_factory=lambda: dict(DEFAULT_SPEAKER_MAP))

    def map(self, speaker: str | None) -> TranscriptSpeaker:
        """Normalize a provider speaker label."""
        if speaker is None or not str(speaker).strip():
            raise UnknownSpeakerError("Missing speaker.")
        key = str(speaker).strip().lower()
        if key not in self.speaker_map:
            raise UnknownSpeakerError(f"Unknown speaker '{speaker}'.")
        return self.speaker_map[key]
