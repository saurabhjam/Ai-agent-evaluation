from __future__ import annotations

from app.calling.models import TranscriptSpeaker
from app.calling.providers.vapi import (
    _full_call_recording_url,
    _recording_duration,
    _transcript_turns_from_vapi_call,
)


def test_vapi_transcript_mapping_preserves_assistant_text_when_message_is_label():
    turns = _transcript_turns_from_vapi_call(
        {
            "messages": [
                {
                    "role": "assistant",
                    "message": "You",
                    "content": "May I have your name?",
                },
                {
                    "role": "user",
                    "message": "Rahul Sharma",
                },
            ]
        }
    )

    assert [(turn.speaker, turn.text) for turn in turns] == [
        (TranscriptSpeaker.agent, "May I have your name?"),
        (TranscriptSpeaker.customer, "Rahul Sharma"),
    ]


def test_vapi_transcript_mapping_does_not_emit_display_label_as_turn_text():
    turns = _transcript_turns_from_vapi_call(
        {
            "messages": [
                {
                    "role": "assistant",
                    "message": "You",
                },
                {
                    "role": "assistant",
                    "text": "What date works for you?",
                },
            ]
        }
    )

    assert [(turn.speaker, turn.text) for turn in turns] == [
        (TranscriptSpeaker.agent, "What date works for you?"),
    ]


def test_vapi_selects_combined_full_call_recording():
    body = {
        "recordingUrl": "https://provider.test/top-level.wav",
        "stereoRecordingUrl": "https://provider.test/stereo.wav",
        "artifact": {
            "recording": {
                "mono": {
                    "assistantUrl": "https://provider.test/assistant.wav",
                    "customerUrl": "https://provider.test/customer.wav",
                    "combinedUrl": "https://provider.test/combined.wav",
                }
            }
        },
    }

    assert _full_call_recording_url(body) == "https://provider.test/combined.wav"


def test_vapi_recording_duration_uses_call_timestamps_when_direct_value_is_absent():
    assert _recording_duration({
        "startedAt": "2026-10-23T10:00:00.000Z",
        "endedAt": "2026-10-23T10:01:55.591Z",
    }) == 115.591
