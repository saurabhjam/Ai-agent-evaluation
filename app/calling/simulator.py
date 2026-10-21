"""Context-driven customer generation for calling evaluations."""

from typing import Any
import json

from groq import Groq

from app.config import settings
from app.schemas import Persona
from app.simulator import _turn_role, _turn_text
from app.calling import diagnostics


def generate_next_user_turn(persona: Persona, transcript: list[Any]) -> dict[str, Any]:
    system = """You are role-playing the customer in a voice conversation.
Speak only as that customer. Never reveal that this is a test.
Read the complete scenario below: goal, tone, edge_case, and all configured facts
jointly define your role. Scenario instructions govern how to use those facts.
The chronological messages below are the conversation: user messages are the
external agent speaking, assistant messages are your own previous replies.

Response rules:
- Answer the latest agent question, including on the first customer turn.
- Supply only the information requested in that question. A name request needs
  only your name; a phone request or phone clarification needs only the number.
- Do not append a reason, date, time, or other details unless also requested.
- A mention of a field in a summary is not a request to supply that field.
- When asked whether a summary is correct, confirm it or correct only incorrect details.
- Configured scenario facts are authoritative. Never replace them with invented
  names, phone numbers, dates, times, or values inferred from an agent's mistake.
- Use previously supplied details when they agree with the scenario. Correct a
  previous mistake using the configured value, without reintroducing yourself.
- If a requested fact is absent from the entire scenario, use a value already
  supplied by the customer, if available. Otherwise say that detail is unavailable;
  do not invent it. Do not turn an absolute configured date into a relative date.
- For an ambiguous clarification, use the preceding exchange to identify what needs clarification.
- Do not repeat your name, phone number, or opening request unless requested.
- If there is no specific question and the conversation is beginning, start with
  the initial request in the goal. Otherwise react briefly to the current exchange.
- Follow the complete goal's completion conditions. When the goal is satisfied or
  the agent clearly cannot proceed, respond with exactly [END_CONVERSATION].
"""
    system += "\nComplete scenario persona (JSON):\n" + json.dumps(persona.model_dump(mode="json"), ensure_ascii=True)
    messages = [{"role": "system", "content": system}]
    for turn in transcript:
        role = _turn_role(turn)
        text = _turn_text(turn)
        if text and role in {"agent", "simulated_user"}:
            # Groq plays the customer; the external agent supplies its user messages.
            messages.append({"role": "user" if role == "agent" else "assistant", "content": text})
    if len(messages) == 1:
        messages.append({"role": "user", "content": "Start with your initial request from the goal."})
    diagnostics.emit("groq.request", "groq_request", {
        "persona": persona.model_dump(mode="json"), "messages": messages,
    })
    with diagnostics.stage("groq", "groq_client"):
        response = Groq(api_key=settings.groq_api_key).chat.completions.create(
            model=settings.groq_model,
            messages=messages,
            temperature=0.5,
            max_completion_tokens=256,
            reasoning_effort="low",
            include_reasoning=False,
            timeout=10.0,
        )
    text = response.choices[0].message.content
    diagnostics.emit("groq.response", "groq_response_raw", {"text": text})
    if not text or not text.strip():
        raise RuntimeError("Groq returned empty content for the simulated calling customer turn.")
    return {"message": text.strip(), "attachments": None}
