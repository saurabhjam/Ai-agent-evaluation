"""Stateful, scenario-grounded simulated caller for calling evaluations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import re
from typing import Any

from groq import Groq

from app.calling import diagnostics
from app.calling.scenario import CallingScenario, CallingSimulatorConfig
from app.config import settings
from app.schemas import Persona, TestScenario
from app.simulator import _turn_role, _turn_text


_PERSONA_MODEL_FIELDS = {"goal", "tone", "edge_case"}
_PLACEHOLDER = re.compile(r"\{\{fact:([a-zA-Z0-9_.-]+)\}\}")
_VALUE_LIKE = re.compile(
    r"(?:\b\d[\d\s().+@:/_-]{2,}\b|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)
_ROLE_REVERSAL = re.compile(
    r"(?:\b(?:may|can|could|would)\s+i\s+(?:have|get|take)\b|"
    r"\b(?:please\s+)?(?:provide|share|tell)\s+me\b|"
    r"\bwhat\s+is\s+your\b)",
    re.IGNORECASE,
)
_CONFIRMATION = re.compile(
    r"(?:\b(?:is that|is this|everything|details?).*\b(?:correct|right|accurate)\b|"
    r"\b(?:correct|right|accurate)\b[^.]*\?)",
    re.IGNORECASE,
)
_CLARIFICATION = re.compile(
    r"\b(?:clarify|repeat|again|did you (?:say|mean)|which|what was)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PersonaFact:
    key: str
    canonical: str
    spoken: str
    aliases: tuple[str, ...]
    initial_value: str | None = None
    corrected_value: str | None = None


@dataclass
class PersonaState:
    facts: dict[str, PersonaFact]
    disclosed_fields: set[str] = field(default_factory=set)
    corrected_fields: set[str] = field(default_factory=set)
    requested_fields: list[str] = field(default_factory=list)
    turn_number: int = 0
    last_agent_utterance: str = ""


class AgentTurnIntentType(str, Enum):
    REQUEST_FACT = "request_fact"
    CONFIRM_FACT = "confirm_fact"
    ACKNOWLEDGE_FACT = "acknowledge_fact"
    REQUEST_CORRECTION = "request_correction"
    TASK_CONFIRMATION = "task_confirmation"
    CLOSING = "closing"
    OTHER = "other"


@dataclass(frozen=True)
class AgentTurnIntent:
    intent: AgentTurnIntentType
    mentioned_fields: tuple[str, ...] = ()
    requested_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResponsePlan:
    action: str
    fields: tuple[str, ...] = ()
    intent: AgentTurnIntentType = AgentTurnIntentType.OTHER


class StatefulCallingSimulator:
    """Select authoritative content first, then ask Groq only for phrasing."""

    def __init__(self, scenario: CallingScenario | TestScenario):
        self.scenario = scenario
        self.config = getattr(scenario, "calling_simulator", CallingSimulatorConfig())
        self.state = PersonaState(facts=_persona_facts(scenario.persona, self.config))

    @property
    def allow_incomplete_utterance(self) -> bool:
        return self.config.mode == "interruption"

    def __call__(self, persona: Persona, transcript: list[Any]) -> dict[str, Any]:
        latest_agent = _latest_agent_text(transcript)
        if not latest_agent:
            return {"message": "", "spoken_message": "", "attachments": None}

        intent = _interpret_agent_turn(latest_agent, transcript, self.state)
        plan = self._plan(intent)
        canonical_values = {key: self._value_for(key, spoken=False) for key in plan.fields}
        spoken_values = {key: self._value_for(key, spoken=True) for key in plan.fields}
        template = self._naturalize(plan, latest_agent)
        fallback_triggered = not _valid_template(template, plan.fields, self.state.facts)
        if fallback_triggered:
            template = _fallback_template(plan)

        canonical = _render(template, canonical_values).strip()
        spoken = _render(template, spoken_values).strip()
        if not canonical or _ROLE_REVERSAL.search(canonical):
            fallback_triggered = True
            template = _fallback_template(plan)
            canonical = _render(template, canonical_values).strip()
            spoken = _render(template, spoken_values).strip()

        communicated_fields = [
            key for key in plan.fields
            if canonical_values.get(key) and canonical_values[key].lower() in canonical.lower()
        ]
        contract_valid = _response_contract_valid(
            canonical,
            plan.fields,
            communicated_fields,
            self.state.facts,
        )
        self.state.requested_fields = list(intent.requested_fields)
        self.state.disclosed_fields.update(communicated_fields)
        self.state.turn_number += 1
        self.state.last_agent_utterance = latest_agent
        diagnostics.emit(
            "simulator.contract",
            "calling_simulator",
            {
                "action": plan.action,
                "intent": intent.intent.value,
                "mentioned_fields": list(intent.mentioned_fields),
                "requested_fields": list(intent.requested_fields),
                "allowed_fields": list(plan.fields),
                "communicated_fields": communicated_fields,
                "fallback_triggered": fallback_triggered,
                "contract_valid": contract_valid,
            },
        )
        return {
            "message": canonical,
            "spoken_message": spoken,
            "attachments": None,
            "disclosed_fields": communicated_fields,
            "simulator_contract": {
                "valid": contract_valid,
                "action": plan.action,
                "intent": intent.intent.value,
                "mentioned_fields": list(intent.mentioned_fields),
                "requested_fields": list(intent.requested_fields),
                "allowed_fields": list(plan.fields),
                "communicated_fields": communicated_fields,
                "fallback_triggered": fallback_triggered,
            },
        }

    def _plan(self, intent: AgentTurnIntent) -> ResponsePlan:
        if intent.intent in {AgentTurnIntentType.CONFIRM_FACT, AgentTurnIntentType.TASK_CONFIRMATION}:
            return ResponsePlan("confirm", intent=intent.intent)
        if intent.intent == AgentTurnIntentType.CLOSING:
            return ResponsePlan("closing", intent=intent.intent)
        if intent.intent == AgentTurnIntentType.REQUEST_CORRECTION:
            if self.config.mode == "correction" and intent.mentioned_fields:
                return ResponsePlan("facts", intent.mentioned_fields, intent.intent)
            return ResponsePlan("confirm", intent=intent.intent)

        requested = list(intent.requested_fields)

        refused = set(self.config.refuse_fields)
        requested = [key for key in requested if key not in refused]
        if requested:
            if self.config.mode == "context_retention":
                requested = _dedupe([*requested, *self.config.volunteer_fields])
            return ResponsePlan(
                "facts",
                tuple(key for key in requested if key in self.state.facts),
                intent.intent,
            )
        if any(key in refused for key in intent.requested_fields):
            return ResponsePlan("refuse", intent=intent.intent)
        if self.state.turn_number == 0:
            fields = tuple(key for key in self.config.volunteer_fields if key in self.state.facts)
            return ResponsePlan("opening", fields, intent.intent)
        return ResponsePlan("acknowledge", intent=intent.intent)

    def _value_for(self, key: str, *, spoken: bool) -> str:
        fact = self.state.facts[key]
        value = fact.spoken if spoken else fact.canonical
        field_config = self.config.fields.get(key)
        if self.config.mode == "clarification" and fact.initial_value is not None:
            if key not in self.state.disclosed_fields:
                value = _spoken_value(fact.initial_value, field_config) if spoken else fact.initial_value
        if self.config.mode == "correction" and fact.initial_value is not None:
            if key not in self.state.disclosed_fields:
                value = _spoken_value(fact.initial_value, field_config) if spoken else fact.initial_value
            else:
                self.state.corrected_fields.add(key)
                corrected = fact.corrected_value or fact.canonical
                value = _spoken_value(corrected, field_config) if spoken else corrected
        return value

    def _naturalize(self, plan: ResponsePlan, latest_agent: str) -> str:
        if plan.action == "opening" and self.config.opening_message:
            return self.config.opening_message + _field_suffix(plan.fields)
        allowed = {key: f"{{{{fact:{key}}}}}" for key in plan.fields}
        prompt = (
            "You are the CUSTOMER in a voice call. The external speaker is the AGENT being evaluated.\n"
            "Write one brief natural customer reply using only the supplied placeholders.\n"
            "Do not ask for customer information, switch roles, repeat the question, invent values, "
            "or add placeholders. Return plain text only.\n"
            f"Action: {plan.action}\n"
            f"Agent turn intent: {plan.intent.value}\n"
            f"Customer tone: {self.scenario.persona.tone}\n"
            f"Scenario goal: {self.scenario.persona.goal}\n"
            f"Scenario edge case: {self.scenario.persona.edge_case or ''}\n"
            f"Latest complete agent utterance: {latest_agent}\n"
            f"Allowed placeholders: {json.dumps(allowed, sort_keys=True)}"
        )
        diagnostics.emit(
            "groq.request",
            "groq_request",
            {
                "action": plan.action,
                "intent": plan.intent.value,
                "allowed_fields": list(plan.fields),
                "latest_agent": latest_agent,
            },
        )
        with diagnostics.stage("groq", "groq_client"):
            response = Groq(api_key=settings.groq_api_key).chat.completions.create(
                model=settings.groq_model,
                messages=[{"role": "system", "content": prompt}],
                temperature=0.2,
                max_completion_tokens=96,
                reasoning_effort="low",
                include_reasoning=False,
                timeout=10.0,
            )
        text = str(response.choices[0].message.content or "").strip()
        diagnostics.emit("groq.response", "groq_response_raw", {"text": text})
        return text


def generate_next_user_turn(persona: Persona, transcript: list[Any]) -> dict[str, Any]:
    """Compatibility entry point; reconstruct basic progress from supplied history."""
    scenario = CallingScenario(
        scenario_id="calling-simulator",
        agent={"channel": "calling", "adapter": "simulator"},
        persona=persona.model_dump(mode="json"),
    )
    simulator = StatefulCallingSimulator(scenario)
    simulator.state.turn_number = sum(1 for turn in transcript if _turn_role(turn) == "simulated_user")
    customer_text = "\n".join(
        _turn_text(turn) for turn in transcript if _turn_role(turn) == "simulated_user"
    ).lower()
    simulator.state.disclosed_fields = {
        key for key, fact in simulator.state.facts.items() if fact.canonical.lower() in customer_text
    }
    agent_texts = [_turn_text(turn) for turn in transcript if _turn_role(turn) == "agent"]
    if len(agent_texts) > 1:
        prior = _interpret_agent_turn(agent_texts[-2], transcript[:-1], simulator.state)
        simulator.state.requested_fields = list(prior.requested_fields)
    result = simulator(persona, transcript)
    return {"message": result.get("message", ""), "attachments": result.get("attachments")}


def _persona_facts(persona: Persona, config: CallingSimulatorConfig) -> dict[str, PersonaFact]:
    raw = persona.model_dump(mode="json")
    facts: dict[str, PersonaFact] = {}
    for key, value in raw.items():
        if key in _PERSONA_MODEL_FIELDS or value is None or isinstance(value, (dict, list)):
            continue
        canonical = str(value).strip()
        if not canonical:
            continue
        field_config = config.fields.get(key)
        aliases = _aliases_for(key, field_config.aliases if field_config else [])
        facts[key] = PersonaFact(
            key=key,
            canonical=canonical,
            spoken=_spoken_value(canonical, field_config),
            aliases=tuple(aliases),
            initial_value=str(field_config.initial_value) if field_config and field_config.initial_value is not None else None,
            corrected_value=str(field_config.corrected_value) if field_config and field_config.corrected_value is not None else None,
        )
    return facts


def _aliases_for(key: str, configured: list[str]) -> list[str]:
    words = [part for part in re.split(r"[_\-.]+", key.lower()) if part]
    derived = [" ".join(words)]
    return _dedupe([*configured, *derived])


def _mentioned_fields(agent_text: str, facts: dict[str, PersonaFact]) -> list[str]:
    normalized = " ".join(agent_text.lower().split())
    matches: list[tuple[int, str]] = []
    for key, fact in facts.items():
        positions = [normalized.find(alias.lower()) for alias in fact.aliases if alias and alias.lower() in normalized]
        if positions:
            matches.append((min(positions), key))
    return [key for _, key in sorted(matches)]


def _interpret_agent_turn(
    agent_text: str,
    recent_transcript: list[Any],
    state: PersonaState,
) -> AgentTurnIntent:
    mentioned = tuple(_mentioned_fields(agent_text, state.facts))
    normalized = " ".join(agent_text.lower().split())

    if re.search(
        r"\b(?:anything|something) else\b|\belse (?:i|we) can\b|"
        r"\b(?:is that|will that be) all\b|\bthank you for (?:calling|contacting)\b",
        normalized,
    ):
        return AgentTurnIntent(AgentTurnIntentType.CLOSING, mentioned)

    correction_offer = re.search(
        r"\b(?:would you like|do you want|any|please)\b[^?.;]*\b(?:correct|correction|change|update)s?\b",
        normalized,
    )
    if correction_offer:
        return AgentTurnIntent(AgentTurnIntentType.REQUEST_CORRECTION, mentioned)

    if _CONFIRMATION.search(agent_text) or re.search(
        r"\b(?:can|could|would)\s+you\s+confirm\b|\bplease confirm\b",
        normalized,
    ):
        intent = (
            AgentTurnIntentType.CONFIRM_FACT
            if len(mentioned) == 1
            else AgentTurnIntentType.TASK_CONFIRMATION
        )
        return AgentTurnIntent(intent, mentioned)

    requested = tuple(_explicitly_requested_fields(agent_text, state.facts))
    if requested:
        return AgentTurnIntent(AgentTurnIntentType.REQUEST_FACT, mentioned, requested)

    if _CLARIFICATION.search(agent_text):
        contextual = tuple(state.requested_fields)
        if not contextual:
            contextual = _last_requested_fields(recent_transcript, state.facts)
        if contextual:
            return AgentTurnIntent(AgentTurnIntentType.REQUEST_FACT, mentioned, contextual)

    if mentioned:
        return AgentTurnIntent(AgentTurnIntentType.ACKNOWLEDGE_FACT, mentioned)
    if re.search(r"\b(?:thank you|thanks|got it|understood)\b", normalized):
        return AgentTurnIntent(AgentTurnIntentType.ACKNOWLEDGE_FACT)
    return AgentTurnIntent(AgentTurnIntentType.OTHER)


def _explicitly_requested_fields(agent_text: str, facts: dict[str, PersonaFact]) -> list[str]:
    clauses = [part.strip() for part in re.split(r"[?.;!]", agent_text.lower()) if part.strip()]
    matches: list[str] = []
    for clause in clauses:
        request_language = bool(re.search(
            r"\b(?:what|which)\b|"
            r"\b(?:may|can|could|would)\s+i\s+(?:have|get|take|know)\b|"
            r"\b(?:please\s+)?(?:provide|share|give|tell|repeat|clarify)\b|"
            r"\b(?:do|would|could|can)\s+you\s+(?:provide|share|give|tell|repeat|clarify)\b|"
            r"\b(?:need|require)\s+(?:to\s+(?:know|have)\s+)?your\b",
            clause,
        ))
        if not request_language:
            continue
        for key in _mentioned_fields(clause, facts):
            if key not in matches:
                matches.append(key)
    return matches


def _last_requested_fields(transcript: list[Any], facts: dict[str, PersonaFact]) -> tuple[str, ...]:
    for turn in reversed(transcript[:-1]):
        if _turn_role(turn) != "agent":
            continue
        requested = _explicitly_requested_fields(_turn_text(turn), facts)
        if requested:
            return tuple(requested)
    return ()


def _spoken_value(value: str, config: Any) -> str:
    if config and config.spoken:
        return config.spoken
    speak_as = config.speak_as if config else "natural"
    if speak_as == "digits":
        names = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine"}
        return " ".join(names.get(char, char) for char in str(value) if not char.isspace())
    if speak_as == "characters":
        return " ".join(str(value))
    if speak_as == "email":
        return str(value).replace("@", " at ").replace(".", " dot ")
    return str(value)


def _valid_template(
    template: str,
    allowed_fields: tuple[str, ...],
    facts: dict[str, PersonaFact],
) -> bool:
    if not template or _ROLE_REVERSAL.search(template) or "?" in template:
        return False
    placeholders = _PLACEHOLDER.findall(template)
    if any(key not in allowed_fields for key in placeholders):
        return False
    if allowed_fields and any(key not in placeholders for key in allowed_fields):
        return False
    scrubbed = _PLACEHOLDER.sub("", template)
    if "{" in scrubbed or "}" in scrubbed:
        return False
    normalized = scrubbed.lower()
    if any(
        value and value.lower() in normalized
        for fact in facts.values()
        for value in (fact.canonical, fact.spoken)
    ):
        return False
    return _VALUE_LIKE.search(scrubbed) is None


def _response_contract_valid(
    response: str,
    requested_fields: tuple[str, ...],
    communicated_fields: list[str],
    facts: dict[str, PersonaFact],
) -> bool:
    if requested_fields and set(communicated_fields) != set(requested_fields):
        return False
    normalized = response.lower()
    return not any(
        key not in requested_fields
        and any(value and value.lower() in normalized for value in (fact.canonical, fact.spoken))
        for key, fact in facts.items()
    )


def _fallback_template(plan: ResponsePlan) -> str:
    if plan.fields:
        values = [f"{{{{fact:{key}}}}}" for key in plan.fields]
        if len(values) == 1:
            return values[0] + "."
        return ", ".join(values[:-1]) + " and " + values[-1] + "."
    if plan.action == "confirm":
        return "Yes, that's correct."
    if plan.action == "closing":
        return "No, that's all. Thank you."
    if plan.action == "refuse":
        return "I'd rather not provide that information."
    if plan.action == "opening":
        return "I'd like help with my request."
    return "Okay."


def _field_suffix(fields: tuple[str, ...]) -> str:
    if not fields:
        return ""
    return " " + _fallback_template(ResponsePlan("facts", fields))


def _render(template: str, values: dict[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda match: values.get(match.group(1), ""), template)


def _latest_agent_text(transcript: list[Any]) -> str:
    for turn in reversed(transcript):
        if _turn_role(turn) == "agent":
            return _turn_text(turn)
    return ""


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result
