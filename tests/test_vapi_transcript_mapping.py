from __future__ import annotations

from app.calling.models import TranscriptSpeaker
from app.calling.providers.vapi import _transcript_turns_from_vapi_call


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
