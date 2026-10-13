from __future__ import annotations

import pytest

from app.calling.models import TranscriptSpeaker
from app.calling.speaker_mapper import SpeakerMapper, UnknownSpeakerError


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("speaker_0", TranscriptSpeaker.customer),
        ("channel_0", TranscriptSpeaker.customer),
        ("customer", TranscriptSpeaker.customer),
        ("caller", TranscriptSpeaker.customer),
        ("simulated_user", TranscriptSpeaker.customer),
        ("speaker_1", TranscriptSpeaker.agent),
        ("channel_1", TranscriptSpeaker.agent),
        ("assistant", TranscriptSpeaker.agent),
        ("agent", TranscriptSpeaker.agent),
        ("callee", TranscriptSpeaker.agent),
    ],
)
def test_speaker_mapper_normalizes_supported_speakers(source, expected):
    assert SpeakerMapper().map(source) == expected


def test_speaker_mapper_rejects_missing_speaker():
    with pytest.raises(UnknownSpeakerError):
        SpeakerMapper().map(None)


def test_speaker_mapper_rejects_unknown_speaker():
    with pytest.raises(UnknownSpeakerError):
        SpeakerMapper().map("narrator")
