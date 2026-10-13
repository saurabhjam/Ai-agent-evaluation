from __future__ import annotations

import pytest

from app.calling.models import CallTranscriptTurn, NormalizedCallTranscript, TranscriptSpeaker
from app.calling.transcript_validator import TranscriptValidationError, TranscriptValidator


def _transcript(turns):
    return NormalizedCallTranscript(session_id="session-1", run_id="run-1", turns=turns)


def test_transcript_validator_accepts_valid_transcript():
    TranscriptValidator().validate(
        _transcript(
            [
                CallTranscriptTurn(
                    speaker=TranscriptSpeaker.customer,
                    text="Hello",
                    turn_index=0,
                    start_time=0.0,
                    end_time=1.0,
                ),
                CallTranscriptTurn(
                    speaker=TranscriptSpeaker.agent,
                    text="Hi",
                    turn_index=1,
                    start_time=1.5,
                    end_time=2.0,
                ),
            ]
        )
    )


@pytest.mark.parametrize(
    "turns",
    [
        [],
        [CallTranscriptTurn(speaker=TranscriptSpeaker.customer, text="", turn_index=0)],
        [CallTranscriptTurn(speaker=TranscriptSpeaker.customer, text="Bad", turn_index=0, start_time=2, end_time=1)],
        [
            CallTranscriptTurn(speaker=TranscriptSpeaker.customer, text="Second", turn_index=0, start_time=2),
            CallTranscriptTurn(speaker=TranscriptSpeaker.agent, text="First", turn_index=1, start_time=1),
        ],
        [
            CallTranscriptTurn(speaker=TranscriptSpeaker.customer, text="A", turn_index=0, start_time=1, end_time=2),
            CallTranscriptTurn(speaker=TranscriptSpeaker.agent, text="B", turn_index=1, start_time=1, end_time=2),
        ],
    ],
)
def test_transcript_validator_rejects_invalid_transcripts(turns):
    with pytest.raises(TranscriptValidationError):
        TranscriptValidator().validate(_transcript(turns))
