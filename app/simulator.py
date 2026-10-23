"""
Simulated caller/user, driven by a local Ollama model.

Given a persona and the conversation so far, generates the next thing the
"user" says. Kept deliberately model-agnostic in prompt design so a small
local model (7-8B) is good enough here — this is generation, not judgment.
"""

from __future__ import annotations

import logging
import time
from groq import Groq
import re
import json

logger = logging.getLogger(__name__)

from app.config import settings
from app.schemas import Persona
from typing import Any

SYSTEM_TEMPLATE = """You are role-playing as a user talking to a customer support agent.

Persona name: {name}
Your goal: {goal}
Your tone: {tone}
{edge_case_line}

Scenario facts (authoritative JSON):
{scenario_context}

Behavior instructions and hard constraints (authoritative JSON):
{behavior_constraints}

Rules:
- Speak ONLY as the user, in first person. Never break character.
- Never reveal you are an AI or that this is a test.
- Keep each message short and natural, like a real chat message (1-3 sentences).
- Base the reply on the latest agent message, the persona goal, and the conversation history.
- Treat scenario facts as the source of truth for material details. You may paraphrase them, but must not replace or contradict them.
- Treat negative behavior instructions (for example, do not invent, disclose, assume, or provide) as hard constraints that override conversational convenience.
- Never introduce a material fact unless it is supplied by the scenario, established in the conversation, or offered by the agent as a workflow choice that the scenario permits you to choose.
- If requested information is unavailable or prohibited by the scenario, say it is unavailable and follow any scenario instruction about how to respond. Do not fabricate it to advance the workflow.
- Agent-provided information may be used only when it advances the goal and does not contradict scenario facts or behavior constraints.
- Do not restart the conversation or repeat the opening request after the conversation has started.
- Do not reveal persona information until the agent asks for it or it is needed to satisfy the latest request.
- If the agent asks for information you already provided, politely repeat only that information.
- Use the "information not yet provided" list as private state. Share only items requested by the latest agent message.
- If the agent asks multiple questions together, answer all of those questions naturally.
- If the latest agent message is only a greeting and no user request has been made yet, start with the initial request from the goal.
- If the agent has fully satisfied your goal, respond with exactly: [END_CONVERSATION]
- If the agent clearly says the goal cannot be completed, respond with exactly: [END_CONVERSATION]
- Otherwise, react naturally to what the agent just said and push toward your goal.
"""

_INFO_TOKEN_PATTERN = re.compile(
    r"""
    \b(?:January|February|March|April|May|June|July|August|September|October|November|December)
       \s+\d{1,2},?\s+\d{4}\b
    |\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\b
    |\b\d[\d\s().:+-]{2,}\d\b
    |\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b
    """,
    re.VERBOSE,
)

_FIELD_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "name": (
        re.compile(r"\b(?:your|full|first|last)?\s*name\b", re.IGNORECASE),
    ),
    "phone": (
        re.compile(r"\b(?:phone|mobile|cell|telephone|contact)\s*(?:number)?\b", re.IGNORECASE),
    ),
    "date": (
        re.compile(r"\b(?:date|day)\b", re.IGNORECASE),
    ),
    "time": (
        re.compile(r"\btime\b", re.IGNORECASE),
    ),
    "reason": (
        re.compile(r"\b(?:reason|purpose|why|what.*(?:for|about))\b", re.IGNORECASE),
    ),
    "email": (
        re.compile(r"\b(?:email|e-mail)\b", re.IGNORECASE),
    ),
    "number": (
        re.compile(r"\b(?:account|confirmation|reference|policy|claim|booking|reservation|order|case|ticket|id)\s*(?:number|id)?\b", re.IGNORECASE),
    ),
}

_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_DATE_PATTERN = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}\b",
    re.IGNORECASE,
)
_TIME_PATTERN = re.compile(r"\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\b")
_PHONE_PATTERN = re.compile(r"\b(?:\+?\d[\d\s().-]{7,}\d)\b")


def _build_prompt(
    persona: Persona,
    transcript: list[Any],
    *,
    scenario_context: dict[str, Any] | None = None,
    behavior_constraints: list[str] | None = None,
) -> list[dict]:
    edge_case_line = f"Edge-case behavior to weave in: {persona.edge_case}" if persona.edge_case else ""
    system = SYSTEM_TEMPLATE.format(
        name=persona.name,
        goal=persona.goal,
        tone=persona.tone,
        edge_case_line=edge_case_line,
        scenario_context=json.dumps(scenario_context or {}, ensure_ascii=True, sort_keys=True),
        behavior_constraints=json.dumps(behavior_constraints or [], ensure_ascii=True),
    )

    history_lines = []
    user_lines = []
    latest_agent_message = ""
    for turn in transcript:
        role = _turn_role(turn)
        content = _turn_text(turn)
        speaker_label = "You (user)" if role == "simulated_user" else "Agent"
        history_lines.append(f"{speaker_label}: {content}")
        if role == "simulated_user" and content:
            user_lines.append(content)
        elif role == "agent" and content:
            latest_agent_message = content
    history = "\n".join(history_lines) if history_lines else "(conversation not started yet)"
    prior_user_messages = "\n".join(f"- {line}" for line in user_lines) if user_lines else "- None yet"
    provided_items, missing_items = _persona_information_state(
        persona,
        user_lines,
        scenario_context=scenario_context,
    )
    request_analysis = _analyze_latest_agent_request(persona, latest_agent_message, user_lines)
    provided_info = "\n".join(f"- {item}" for item in provided_items) if provided_items else "- None detected yet"
    missing_info = "\n".join(f"- {item}" for item in missing_items) if missing_items else "- None detected"
    requested = "\n".join(f"- {item}" for item in request_analysis["requested_fields"]) or "- None detected"
    answered = "\n".join(f"- {item}" for item in request_analysis["already_answered"]) or "- None detected"
    unanswered = "\n".join(f"- {item}" for item in request_analysis["unanswered"]) or "- None detected"
    latest_agent = latest_agent_message or "(no agent message yet)"

    user_content = (
        f"Conversation so far:\n{history}\n\n"
        f"Latest agent message:\n{latest_agent}\n\n"
        f"Latest question analysis:\n"
        f"Requested fields:\n{requested}\n"
        f"Already answered requested fields:\n{answered}\n"
        f"Unanswered requested fields:\n{unanswered}\n\n"
        f"Prior user messages:\n{prior_user_messages}\n\n"
        f"Information already provided:\n{provided_info}\n\n"
        f"Information not yet provided:\n{missing_info}\n\n"
        "Decision priority: (1) preserve scenario truth and hard constraints, "
        "(2) continue pursuing the persona goal, (3) use conversation state, "
        "(4) select or use agent-provided workflow information only when compatible, and "
        "(5) otherwise respond naturally without fabricating missing material information. "
        "First answer the latest agent question using only supported, unanswered requested fields. "
        "Do not restate the overall goal unless the latest agent message specifically asks what you need or how they can help. "
        "Decide the next user response from the current state. Answer the latest agent message directly. "
        "Do not re-send the opening request once a prior user message exists. "
        "If this is the first user turn, start with the user's initial request from the persona goal. "
        "Your next message:"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content}
    ]


def _persona_information_state(
    persona: Persona,
    user_lines: list[str],
    *,
    scenario_context: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    context_text = " ".join(
        str(value) for value in (scenario_context or {}).values() if value not in (None, "")
    )
    persona_text = ". ".join(
        part for part in [persona.goal, persona.edge_case or "", context_text] if part
    )
    name = str(persona.name or "").strip()
    candidates = _extract_information_candidates(persona_text)
    if name and name.lower() not in {item.lower() for item in candidates}:
        candidates.insert(0, name)
    provided: list[str] = []
    missing: list[str] = []
    prior_text = "\n".join(user_lines).lower()
    for item in candidates:
        if item.lower() in prior_text:
            provided.append(item)
        else:
            missing.append(item)
    return provided, missing


def _extract_information_candidates(text: str) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []
    for match in _INFO_TOKEN_PATTERN.finditer(text or ""):
        item = re.sub(r"^(?:Provide|Request|Ask|Use|Tell)\s+", "", match.group(0).strip(" .,:;()"))
        if len(item) < 3 or item.lower() in seen:
            continue
        seen.add(item.lower())
        candidates.append(item)
    return candidates


def _analyze_latest_agent_request(persona: Persona, latest_agent_message: str, user_lines: list[str]) -> dict[str, list[str]]:
    requested_values = _requested_values_for_message(persona, latest_agent_message)
    prior_text = "\n".join(user_lines).lower()
    already_answered = [value for value in requested_values if value.lower() in prior_text]
    unanswered = [value for value in requested_values if value.lower() not in prior_text]
    return {
        "requested_fields": requested_values,
        "already_answered": already_answered,
        "unanswered": unanswered,
    }


def _requested_values_for_message(persona: Persona, message: str) -> list[str]:
    return [value for _, value in _requested_answers_for_message(persona, message)]


def _requested_answers_for_message(persona: Persona, message: str) -> list[tuple[str, str]]:
    if not message:
        return []
    requested_types = _requested_field_types(message)
    if not requested_types:
        return []
    values_by_type = _persona_values_by_type(persona)
    values: list[str] = []
    seen: set[str] = set()
    for field_type in requested_types:
        for value in values_by_type.get(field_type, []):
            key = value.lower()
            if key not in seen:
                seen.add(key)
                values.append((field_type, value))
    return values


def _requested_field_types(message: str) -> list[str]:
    requested: list[str] = []
    for field_type, patterns in _FIELD_PATTERNS.items():
        if any(pattern.search(message) for pattern in patterns):
            requested.append(field_type)
    return requested


def _persona_values_by_type(persona: Persona) -> dict[str, list[str]]:
    persona_text = ". ".join(part for part in [persona.goal, persona.edge_case or ""] if part)
    values: dict[str, list[str]] = {
        "name": [str(persona.name).strip()] if getattr(persona, "name", None) else [],
        "phone": _find_unique(_PHONE_PATTERN, persona_text),
        "date": _find_unique(_DATE_PATTERN, persona_text),
        "time": _find_unique(_TIME_PATTERN, persona_text),
        "email": _find_unique(_EMAIL_PATTERN, persona_text),
        "number": [],
        "reason": [],
    }
    typed_values = {value.lower() for items in values.values() for value in items}
    for candidate in _extract_information_candidates(persona_text):
        if candidate.lower() not in typed_values:
            values["number"].append(candidate)
    values["reason"] = _extract_reason_candidates(persona)
    return {key: _dedupe(items) for key, items in values.items()}


def _find_unique(pattern: re.Pattern[str], text: str) -> list[str]:
    return _dedupe(match.group(0).strip(" .,:;()") for match in pattern.finditer(text or ""))


def _dedupe(items) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for item in items:
        value = str(item or "").strip()
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        values.append(value)
    return values


def _extract_reason_candidates(persona: Persona) -> list[str]:
    goal = str(persona.goal or "").strip()
    patterns = [
        r"\breason\s+(?:is|:)\s*([^.;\n]+)",
        r"\b(?:because|as)\s+([^.;\n]+)",
        r"\b(?:about|regarding|for)\s+(?:a|an|the)?\s*([^.;\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, goal, re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .,:;()")
            if value:
                return [value]
    return []


def _question_first_response(persona: Persona, transcript: list[Any]) -> str | None:
    user_lines: list[str] = []
    latest_agent_message = ""
    for turn in transcript:
        role = _turn_role(turn)
        content = _turn_text(turn)
        if role == "simulated_user" and content:
            user_lines.append(content)
        elif role == "agent" and content:
            latest_agent_message = content

    requested_answers = _requested_answers_for_message(persona, latest_agent_message)
    if not requested_answers:
        return None

    prior_text = "\n".join(user_lines).lower()
    missing_answers = [(field_type, value) for field_type, value in requested_answers if value.lower() not in prior_text]
    answers_to_send = missing_answers or requested_answers
    return _format_requested_values_response(answers_to_send)


def _format_requested_values_response(answers: list[tuple[str, str]]) -> str | None:
    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for field_type, value in answers:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((field_type, value))
    if not deduped:
        return None
    if len(deduped) == 1:
        return _format_single_value_response(deduped[0][0], deduped[0][1])
    return " ".join(_format_single_value_response(field_type, value) for field_type, value in deduped)


def _format_single_value_response(field_type: str, value: str) -> str:
    value = str(value).strip()
    if field_type == "name":
        return f"My name is {value}."
    if field_type == "phone":
        return f"My phone number is {value}."
    if field_type == "email":
        return f"My email is {value}."
    if field_type == "date":
        return f"The date is {value}."
    if field_type == "time":
        return f"The time is {value}."
    if field_type == "reason":
        return f"The reason is {value}."
    return f"It is {value}."


def decide_next_user_action(
    persona: Persona,
    transcript: list[Any],
    options: list[dict[str, Any]],
    *,
    scenario_context: dict[str, Any] | None = None,
    behavior_constraints: list[str] | None = None,
) -> dict[str, Any]:
    """Choose a goal-relevant option or produce the next goal-directed message.

    This is the single semantic decision point for interactive chatbot turns.
    The configured persona goal remains authoritative; agent-provided options are
    candidate workflow steps, never replacement objectives.
    """
    if not options:
        generated = generate_next_user_turn(
            persona,
            transcript,
            scenario_context=scenario_context,
            behavior_constraints=behavior_constraints,
        )
        return {**generated, "selected_option_index": None}

    messages = _build_prompt(
        persona,
        transcript,
        scenario_context=scenario_context,
        behavior_constraints=behavior_constraints,
    )
    messages[0]["content"] += """

Interactive decision rules:
- The configured persona goal is immutable and is the authoritative objective.
- Treat agent-provided options only as possible next workflow steps.
- Select an option only when it reasonably advances the goal in the current conversation state.
- Select an option only when it is also compatible with scenario facts and behavior constraints.
- Reject an option that requires an unsupported material assumption, even if it would advance the workflow.
- An agent-provided choice may be selected when the scenario permits choosing it and it does not contradict configured facts or constraints.
- A useful workflow step can be indirectly related to the goal; judge it from the latest agent response and full history, not word overlap.
- Reject options that redirect the user to an unrelated objective, even when the agent recommends them.
- If no option advances the goal, write the natural free-text reply that continues pursuing the configured goal.
- Return JSON only. Do not include Markdown.
"""
    normalized_options = [
        {
            "index": index,
            "label": str(option.get("label") or option.get("title") or option.get("text") or ""),
            "message": str(option.get("message") or option.get("value") or option.get("payload") or option.get("text") or option.get("label") or ""),
        }
        for index, option in enumerate(options)
    ]
    messages[-1]["content"] += (
        "\n\nAvailable agent options (JSON):\n"
        + json.dumps(normalized_options, ensure_ascii=True)
        + "\n\nReturn exactly one JSON object in this schema:\n"
        + '{"action":"select_option","option_index":0}\n'
        + "or:\n"
        + '{"action":"free_text","option_index":null,"text":"goal-directed user reply"}'
    )

    start = time.perf_counter()
    client = Groq(api_key=settings.groq_api_key)
    response = client.chat.completions.create(
        model=settings.groq_model,
        messages=messages,
        temperature=0.2,
        max_completion_tokens=256,
        reasoning_effort="low",
        include_reasoning=False,
        timeout=10.0,
    )
    choice = response.choices[0]
    content = choice.message.content
    raw = str(content or "")
    logger.info(
        "[STAGE: Simulated User Decision Output] content_state=%s content_length=%s "
        "finish_reason=%s has_reasoning=%s",
        _content_state(content),
        len(raw),
        getattr(choice, "finish_reason", None),
        bool(getattr(choice.message, "reasoning", None)),
    )
    try:
        decision = _parse_action_decision(raw)
        result = _validated_action_result(decision, normalized_options)
    except RuntimeError as exc:
        logger.warning(
            "Simulator interactive decision unusable (%s); using grounded free-text fallback",
            str(exc),
        )
        return _grounded_decision_fallback(
            persona,
            transcript,
            scenario_context=scenario_context,
            behavior_constraints=behavior_constraints,
            original_error=exc,
        )

    logger.info(
        "[STAGE: Simulated User Decision] elapsed=%.3fs action=%s option_index=%s",
        time.perf_counter() - start,
        decision["action"],
        result["selected_option_index"],
    )
    return result


def _parse_action_decision(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("Simulator returned an empty interactive decision.")
    candidate = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Simulator returned malformed interactive decision JSON.") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Simulator interactive decision must be a JSON object.")
    action = str(value.get("action") or "").strip().lower()
    if action == "select_option":
        return {"action": action, "option_index": value.get("option_index")}
    if action == "free_text":
        text = value.get("text")
        if text is None:
            text = value.get("message")
        return {"action": action, "option_index": None, "text": text}
    raise RuntimeError("Simulator returned an unsupported interactive action.")


def _validated_action_result(
    decision: dict[str, Any],
    normalized_options: list[dict[str, Any]],
) -> dict[str, Any]:
    action = decision["action"]
    if action == "select_option":
        selected_index = decision.get("option_index")
        if not isinstance(selected_index, int) or isinstance(selected_index, bool):
            raise RuntimeError("Simulator option decision is missing a valid integer option_index.")
        if not 0 <= selected_index < len(normalized_options):
            raise RuntimeError("Simulator option decision index is out of range.")
        message = normalized_options[selected_index]["message"]
        if not message:
            raise RuntimeError("Simulator selected an interactive option without a dispatchable value.")
        return {"message": message, "attachments": None, "selected_option_index": selected_index}

    text = decision.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Simulator free-text decision is empty.")
    return {"message": text.strip(), "attachments": None, "selected_option_index": None}


def _grounded_decision_fallback(
    persona: Persona,
    transcript: list[Any],
    *,
    scenario_context: dict[str, Any] | None,
    behavior_constraints: list[str] | None,
    original_error: RuntimeError,
) -> dict[str, Any]:
    try:
        generated = generate_next_user_turn(
            persona,
            transcript,
            scenario_context=scenario_context,
            behavior_constraints=behavior_constraints,
        )
    except RuntimeError as fallback_error:
        raise RuntimeError(
            "Interactive decision was unusable and grounded fallback generation "
            "did not produce a valid user turn."
        ) from fallback_error

    message = generated.get("message")
    if not isinstance(message, str) or not message.strip():
        raise RuntimeError(
            "Interactive decision was unusable and grounded fallback generation "
            "did not produce a valid user turn."
        ) from original_error
    return {
        "message": message.strip(),
        "attachments": generated.get("attachments"),
        "selected_option_index": None,
    }


def _content_state(content: Any) -> str:
    if content is None:
        return "none"
    if not isinstance(content, str):
        return "non_string"
    if not content:
        return "empty"
    if not content.strip():
        return "whitespace"
    return "present"


def _turn_role(turn: Any) -> str:
    role = getattr(turn, "role", None)
    if role:
        value = role
    else:
        speaker = getattr(turn, "speaker", None)
        value = getattr(speaker, "value", speaker)
    normalized = str(value or "").strip().lower()
    if normalized in {"user", "customer", "caller", "human", "client", "simulated_user"}:
        return "simulated_user"
    if normalized in {"assistant", "agent", "bot", "ai"}:
        return "agent"
    return "system"


def _turn_text(turn: Any) -> str:
    return str(getattr(turn, "content", getattr(turn, "text", "")) or "").strip()


def generate_next_user_turn(
    persona: Persona,
    transcript: list[Any],
    *,
    scenario_context: dict[str, Any] | None = None,
    behavior_constraints: list[str] | None = None,
) -> dict[str, Any]:
    start = time.perf_counter()
    turn_index = len(transcript) // 2
    try:
        # Scenario-grounded runs must pass through the single generation call so
        # explicit facts and negative constraints can override convenience.
        question_first = None
        if not scenario_context and not behavior_constraints:
            question_first = _question_first_response(persona, transcript)
        if question_first:
            elapsed = time.perf_counter() - start
            logger.info(f"[STAGE: Simulated User Generation] turn_index={turn_index} elapsed={elapsed:.3f}s source=question_first")
            return {"message": question_first, "attachments": None}

        messages = _build_prompt(
            persona,
            transcript,
            scenario_context=scenario_context,
            behavior_constraints=behavior_constraints,
        )

        client = Groq(api_key=settings.groq_api_key)
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=messages,
            temperature=0.5,
            max_completion_tokens=256,
            reasoning_effort="low",
            include_reasoning=False,
            timeout=10.0
        )
        
        text = response.choices[0].message.content
        if not text or not text.strip():
            raise RuntimeError("Groq returned empty content for the simulated user turn. This may be due to reasoning tokens consuming the max_completion_tokens budget.")
            
        text = text.strip()
        attachments = []
        
        # Track previously sent attachments in this session
        sent_counts = {}
        for turn in transcript:
            if _turn_role(turn) == "simulated_user" and getattr(turn, "attachments", None):
                for att in turn.attachments:
                    sent_counts[att] = sent_counts.get(att, 0) + 1
                    
        # Simple extraction of [ATTACHMENT: path/to/file]
        import re
        pattern = r"\[ATTACHMENT:\s*([^\]]+)\]"
        matches = re.findall(pattern, text)
        
        persona_text = f"{persona.goal or ''} {persona.edge_case or ''}"
        
        for match in matches:
            path = match.strip()
            # How many times is this specific attachment explicitly required in the scenario?
            explicit_mentions = persona_text.count(f"[ATTACHMENT: {path}]")
            max_allowed = max(1, explicit_mentions)
            
            if sent_counts.get(path, 0) >= max_allowed:
                logger.info(f"Suppressing duplicate attachment {path}")
            else:
                attachments.append(path)
                sent_counts[path] = sent_counts.get(path, 0) + 1
        
        text = re.sub(pattern, "", text).strip()
            
        elapsed = time.perf_counter() - start
        logger.info(f"[STAGE: Simulated User Generation] turn_index={turn_index} elapsed={elapsed:.3f}s")
        return {"message": text, "attachments": attachments if attachments else None}
    except Exception as e:
        elapsed = time.perf_counter() - start
        logger.error(f"[STAGE: Simulated User Generation FAILED] turn_index={turn_index} elapsed={elapsed:.3f}s exception={type(e).__name__}: {e}")
        raise
