from __future__ import annotations

from unittest.mock import patch

from app.calling.models import CallTranscriptTurn, TranscriptSpeaker
from app.schemas import Persona
from app.simulator import generate_next_user_turn


def test_calling_simulator_prompt_is_state_driven_and_domain_agnostic():
    persona = Persona(
        name="Avery Lee",
        goal="Dispute an unknown transaction and provide only requested account details.",
        tone="Calm",
        edge_case="Do not repeat already provided details unless asked.",
    )
    transcript = [
        CallTranscriptTurn(speaker=TranscriptSpeaker.agent, text="How can I help?", turn_index=0),
        CallTranscriptTurn(speaker=TranscriptSpeaker.customer, text="I need to dispute a transaction.", turn_index=1),
        CallTranscriptTurn(speaker=TranscriptSpeaker.agent, text="May I have the last four digits?", turn_index=2),
    ]

    with patch("app.simulator.Groq") as mock_groq_class:
        mock_client = mock_groq_class.return_value
        mock_client.chat.completions.create.return_value.choices[0].message.content = "The last four digits are 1234."

        reply = generate_next_user_turn(persona, transcript)

    assert reply["message"] == "The last four digits are 1234."
    _, kwargs = mock_client.chat.completions.create.call_args
    prompt = kwargs["messages"][1]["content"]
    assert "Latest agent message:\nMay I have the last four digits?" in prompt
    assert "Prior user messages:\n- I need to dispute a transaction." in prompt
    assert "Answer the latest agent message directly." in prompt
    assert "Information not yet provided:" in prompt
    assert "Do not re-send the opening request once a prior user message exists." in prompt


def test_calling_simulator_treats_customer_transcript_speaker_as_user():
    persona = Persona(
        name="Mira",
        goal="Check hotel reservation status without revealing extra details.",
        tone="Polite",
    )
    transcript = [
        CallTranscriptTurn(speaker=TranscriptSpeaker.customer, text="I want to check my reservation.", turn_index=0),
        CallTranscriptTurn(speaker=TranscriptSpeaker.agent, text="What is your confirmation number?", turn_index=1),
    ]

    with patch("app.simulator.Groq") as mock_groq_class:
        mock_client = mock_groq_class.return_value
        mock_client.chat.completions.create.return_value.choices[0].message.content = "It is ABC123."

        generate_next_user_turn(persona, transcript)

    _, kwargs = mock_client.chat.completions.create.call_args
    prompt = kwargs["messages"][1]["content"]
    assert "You (user): I want to check my reservation." in prompt
    assert "Agent: What is your confirmation number?" in prompt


def test_calling_simulator_tracks_provided_and_missing_goal_information_generically():
    persona = Persona(
        name="Rahul Sharma",
        goal=(
            "Request a service appointment. Provide Rahul Sharma, 9876543210, "
            "October 8, 2026, and 4:00 PM only when asked."
        ),
        tone="Natural",
    )
    transcript = [
        CallTranscriptTurn(speaker=TranscriptSpeaker.customer, text="I need to schedule a service appointment.", turn_index=0),
        CallTranscriptTurn(speaker=TranscriptSpeaker.agent, text="May I have your name?", turn_index=1),
        CallTranscriptTurn(speaker=TranscriptSpeaker.customer, text="My name is Rahul Sharma.", turn_index=2),
        CallTranscriptTurn(speaker=TranscriptSpeaker.agent, text="What phone number should I use?", turn_index=3),
    ]

    with patch("app.simulator.Groq") as mock_groq_class:
        reply = generate_next_user_turn(persona, transcript)

    assert reply["message"] == "My phone number is 9876543210."
    mock_groq_class.assert_not_called()


def test_calling_simulator_answers_latest_name_question_before_goal():
    persona = Persona(
        name="Rahul Sharma",
        goal="Request a consultation. Provide Rahul Sharma and 9876543210 only when asked.",
        tone="Natural",
    )
    transcript = [
        CallTranscriptTurn(speaker=TranscriptSpeaker.customer, text="I want to book a consultation.", turn_index=0),
        CallTranscriptTurn(speaker=TranscriptSpeaker.agent, text="May I have your name?", turn_index=1),
    ]

    with patch("app.simulator.Groq") as mock_groq_class:
        reply = generate_next_user_turn(persona, transcript)

    assert reply["message"] == "My name is Rahul Sharma."
    mock_groq_class.assert_not_called()


def test_calling_simulator_answers_multiple_latest_requested_fields():
    persona = Persona(
        name="Rahul Sharma",
        goal="Request help. Provide Rahul Sharma, 9876543210, October 8, 2026, and 4:00 PM only when asked.",
        tone="Natural",
    )
    transcript = [
        CallTranscriptTurn(speaker=TranscriptSpeaker.customer, text="I need help with this request.", turn_index=0),
        CallTranscriptTurn(speaker=TranscriptSpeaker.agent, text="Can I have your name and phone number?", turn_index=1),
    ]

    with patch("app.simulator.Groq") as mock_groq_class:
        reply = generate_next_user_turn(persona, transcript)

    assert reply["message"] == "My name is Rahul Sharma. My phone number is 9876543210."
    mock_groq_class.assert_not_called()


def test_calling_simulator_first_turn_still_starts_from_goal():
    persona = Persona(
        name="Jordan",
        goal="Ask about filing an insurance claim for a damaged suitcase.",
        tone="Polite",
    )

    with patch("app.simulator.Groq") as mock_groq_class:
        mock_client = mock_groq_class.return_value
        mock_client.chat.completions.create.return_value.choices[0].message.content = (
            "I need help filing an insurance claim for a damaged suitcase."
        )

        generate_next_user_turn(persona, [])

    _, kwargs = mock_client.chat.completions.create.call_args
    prompt = kwargs["messages"][1]["content"]
    assert "Conversation so far:\n(conversation not started yet)" in prompt
    assert "If this is the first user turn, start with the user's initial request from the persona goal." in prompt
