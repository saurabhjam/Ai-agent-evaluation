"""Role-aware, chronological evidence for calling judges and failure analysis."""

from typing import Any

from app.calling.scenario import CallingSimulatorConfig
from app.calling.semantic_values import normalize_structured_value, _observed_candidates
from app.calling.simulator import PersonaState, _persona_facts, _interpret_agent_turn


def build_workflow_evidence(scenario: Any, transcript: list[Any]) -> list[dict[str, Any]]:
    config = getattr(scenario, "calling_simulator", CallingSimulatorConfig())
    state = PersonaState(facts=_persona_facts(scenario.persona, config))
    evidence = []
    pending: list[str] = []
    supplied: set[str] = set()
    last_customer = ""
    for index, message in enumerate(transcript):
        role, text = _get(message, "role"), str(_get(message, "content") or "")
        if role in {"simulated_user", "user", "customer"}:
            communicated = {
                key for key, fact in state.facts.items()
                if _contains_fact(key, fact.canonical, text)
            }
            if not last_customer and config.opening_message and text.strip() == config.opening_message.strip():
                communicated.update(key for key in config.opening_fields if key in state.facts)
            supplied.update(communicated)
            evidence.append({
                "turn_index": index, "source_role": "persona",
                "requested_fields": list(pending),
                "supplied_fields": sorted(communicated),
                "missing_requested_fields": sorted(set(pending) - communicated),
            })
            last_customer = text
        elif role == "agent":
            intent = _interpret_agent_turn(text, transcript[:index + 1], state)
            requested = list(intent.requested_fields)
            unresolved = set(pending) - supplied
            evidence.append({
                "turn_index": index, "source_role": "agent",
                "intent": intent.intent.value,
                "mentioned_fields": list(intent.mentioned_fields),
                "requested_fields": requested,
                "justified_reasks": sorted(set(requested) & unresolved),
                "previously_supplied_requests": sorted(set(requested) & supplied),
                "clarification_requested": any(word in text.lower() for word in ("clarify", "repeat", "correct")),
            })
            if requested:
                pending = requested
                state.requested_fields = requested
    return evidence


def workflow_instructions(evidence: list[dict[str, Any]]) -> str:
    import json
    return (
        "Calling evidence (evaluation annotations, not spoken dialogue): "
        "Judge AGENT behavior separately from PERSONA behavior. A persona non-answer does not "
        "supply a requested fact. Reasking an unresolved field is justified and is not forgetting, "
        "irrelevance or incompleteness. Previously supplied requests can indicate lost context "
        "only when clarification/correction is unnecessary. Do not excuse unrelated agent behavior. "
        "Evaluate outcomes against the original configured goal; do not invent requirements for "
        "confirmed transactions when the goal permits request collection or an explanation. "
        + json.dumps(evidence, separators=(",", ":"))
    )


def _contains_fact(key: str, value: str, text: str) -> bool:
    expected = normalize_structured_value(key, value)
    if value.casefold() in text.casefold():
        return True
    return expected is not None and any(
        normalize_structured_value(key, candidate) == expected
        for candidate in _observed_candidates(key, [text])
    )


def _get(message: Any, key: str) -> Any:
    return message.get(key) if isinstance(message, dict) else getattr(message, key, None)
