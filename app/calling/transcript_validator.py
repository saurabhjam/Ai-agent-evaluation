"""Validation for normalized call transcripts."""

from __future__ import annotations

from dataclasses import dataclass

from app.calling.models import RawCallTranscript


class TranscriptValidationError(ValueError):
    """Raised when a normalized call transcript is invalid."""


@dataclass(frozen=True)
class TranscriptValidator:
    """Validates transcript quality before conversation normalization."""

    def validate(self, transcript: RawCallTranscript) -> None:
        """Validate a normalized call transcript."""
        if not transcript.turns:
            raise TranscriptValidationError("Empty transcript.")

        previous_start: float | None = None
        seen_timestamps: set[tuple[float | None, float | None]] = set()
        for turn in transcript.turns:
            if not turn.speaker:
                raise TranscriptValidationError("Missing speaker.")
            if not turn.text or not turn.text.strip():
                raise TranscriptValidationError("Missing text.")
            if turn.start_time is not None and turn.start_time < 0:
                raise TranscriptValidationError("Invalid timestamps.")
            if turn.end_time is not None and turn.end_time < 0:
                raise TranscriptValidationError("Invalid timestamps.")
            if (
                turn.start_time is not None
                and turn.end_time is not None
                and turn.end_time < turn.start_time
            ):
                raise TranscriptValidationError("Invalid timestamps.")
            if previous_start is not None and turn.start_time is not None and turn.start_time < previous_start:
                raise TranscriptValidationError("Out-of-order timestamps.")
            stamp = (turn.start_time, turn.end_time)
            if stamp != (None, None) and stamp in seen_timestamps:
                raise TranscriptValidationError("Duplicate timestamps.")
            seen_timestamps.add(stamp)
            if turn.start_time is not None:
                previous_start = turn.start_time
