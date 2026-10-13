"""
User Action Engine planners.

Phase 2 remains isolated from runtime execution. These planners produce action
proposals only; they never execute adapter calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.interactive.action_validator import ActionValidator
from app.interactive.capability_registry import CapabilityRegistry, default_capability_registry
from app.interactive.conversation_state import ConversationState
from app.interactive.models import (
    ActionType,
    InteractiveElement,
    InteractiveElementType,
    NormalizedAgentResponse,
    UserAction,
)


@dataclass
class ActionProposal:
    action: UserAction
    confidence: float
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))


class LLMClientProtocol(Protocol):
    def complete_action(self, prompt: str) -> str:
        """Return a JSON action proposal string."""


class RuleBasedFallbackPlanner:
    """
    Deterministic planner used when no LLM client is provided or LLM output is
    invalid.
    """

    def plan(
        self,
        *,
        state: ConversationState,
        adapter_name: str = "rest",
        scenario: Any = None,
        persona: Any = None,
        transcript: list[Any] | None = None,
    ) -> ActionProposal:
        response = state.current_agent_response
        goal_text = self._goal_text(state=state, scenario=scenario, persona=persona)

        if response.interactive:
            element = self._best_interactive_element(response.interactive, goal_text)
            action_type = self._action_type_for_element(element)
            action = UserAction(
                type=action_type,
                target=element.label,
                value=element.action_value(),
                file=element.metadata.get("file"),
            )
            return ActionProposal(
                action=action,
                confidence=0.82,
                reason="Selected the available interactive action that best matches the current goal.",
                metadata={"planner": "rule_based"},
            )

        fallback_text = self._text_from_goal(goal_text)
        return ActionProposal(
            action=UserAction(type=ActionType.send_text, text=fallback_text),
            confidence=0.62,
            reason="No interactive actions were available; proposed a text response from the goal.",
            metadata={"planner": "rule_based"},
        )

    def _best_interactive_element(
        self,
        elements: list[InteractiveElement],
        goal_text: str,
    ) -> InteractiveElement:
        goal_tokens = self._tokens(goal_text)
        if not goal_tokens:
            return elements[0]

        def score(element: InteractiveElement) -> int:
            element_tokens = self._tokens(f"{element.label} {element.value or ''}")
            return len(goal_tokens.intersection(element_tokens))

        return max(elements, key=score)

    def _action_type_for_element(self, element: InteractiveElement) -> ActionType:
        mapping = {
            InteractiveElementType.button: ActionType.click_button,
            InteractiveElementType.quick_reply: ActionType.click_option,
            InteractiveElementType.suggestion_chip: ActionType.click_option,
            InteractiveElementType.dropdown_option: ActionType.select_dropdown,
            InteractiveElementType.menu_item: ActionType.click_option,
            InteractiveElementType.upload_request: ActionType.upload_file,
            InteractiveElementType.confirmation: ActionType.confirm,
            InteractiveElementType.date_picker: ActionType.select_date,
            InteractiveElementType.time_picker: ActionType.select_time,
            InteractiveElementType.link: ActionType.open_link,
        }
        return mapping.get(element.type, ActionType.click_option)

    def _goal_text(self, *, state: ConversationState, scenario: Any, persona: Any) -> str:
        parts = [state.current_goal]
        for source in [persona, getattr(scenario, "persona", None)]:
            if source is None:
                continue
            parts.extend([
                str(getattr(source, "goal", "") or ""),
                str(getattr(source, "edge_case", "") or ""),
            ])
        parts.extend(str(value) for value in state.known_facts.values())
        parts.extend(state.pending_goals)
        return " ".join(part for part in parts if part)

    def _text_from_goal(self, goal_text: str) -> str:
        if not goal_text:
            return "I need help with this."
        lowered = goal_text.lower()
        if "maintenance" in lowered or "leak" in lowered:
            return "I need to report a maintenance issue."
        return goal_text.strip()

    def _tokens(self, text: str) -> set[str]:
        return {
            token.strip(".,!?;:()[]{}\"'").lower()
            for token in text.split()
            if len(token.strip(".,!?;:()[]{}\"'")) >= 3
        }


class LLMActionPlanner:
    """
    Structured LLM planner wrapper.

    The LLM client is injected so this module has no direct dependency on a
    provider SDK. If no client is present or parsing fails, callers should use
    RuleBasedFallbackPlanner.
    """

    def __init__(self, client: LLMClientProtocol | None = None) -> None:
        self.client = client

    def plan(
        self,
        *,
        state: ConversationState,
        adapter_name: str = "rest",
        scenario: Any = None,
        persona: Any = None,
        transcript: list[Any] | None = None,
    ) -> ActionProposal:
        if self.client is None:
            raise RuntimeError("LLMActionPlanner requires an injected LLM client.")

        raw = self.client.complete_action(self._build_prompt(state=state, scenario=scenario, persona=persona, transcript=transcript))
        payload = json.loads(raw)
        action_payload = payload.get("action") or {}
        action = UserAction(
            type=ActionType(action_payload["type"]),
            target=action_payload.get("target"),
            text=action_payload.get("text"),
            value=action_payload.get("value"),
            file=action_payload.get("file"),
            metadata=action_payload.get("metadata") or {},
        )
        return ActionProposal(
            action=action,
            confidence=float(payload.get("confidence", 0.5)),
            reason=str(payload.get("reason", "")),
            metadata={"planner": "llm"},
        )

    def _build_prompt(
        self,
        *,
        state: ConversationState,
        scenario: Any,
        persona: Any,
        transcript: list[Any] | None,
    ) -> str:
        options = [
            {"type": item.type.value, "label": item.label, "value": item.action_value()}
            for item in state.current_agent_response.interactive
        ]
        payload = {
            "goal": state.current_goal,
            "known_facts": state.known_facts,
            "missing_facts": state.missing_facts,
            "agent_response": state.current_agent_response.text,
            "available_actions": options,
            "transcript_length": len(transcript or state.transcript),
        }
        return (
            "Choose the next simulated user action. Return JSON with keys "
            "action, confidence, and reason. Context:\n"
            f"{json.dumps(payload, ensure_ascii=True)}"
        )


class UserActionEngine:
    """Coordinates planner selection and validates proposed actions."""

    def __init__(
        self,
        *,
        llm_planner: LLMActionPlanner | None = None,
        fallback_planner: RuleBasedFallbackPlanner | None = None,
        validator: ActionValidator | None = None,
        capability_registry: CapabilityRegistry | None = None,
    ) -> None:
        self.capabilities = capability_registry or default_capability_registry()
        self.llm_planner = llm_planner
        self.fallback_planner = fallback_planner or RuleBasedFallbackPlanner()
        self.validator = validator or ActionValidator(self.capabilities)

    def propose_action(
        self,
        *,
        state: ConversationState,
        adapter_name: str = "rest",
        scenario: Any = None,
        persona: Any = None,
        transcript: list[Any] | None = None,
        observation: NormalizedAgentResponse | None = None,
    ) -> ActionProposal:
        if observation is not None:
            state.current_agent_response = observation

        proposal = self._planner_proposal(
            state=state,
            adapter_name=adapter_name,
            scenario=scenario,
            persona=persona,
            transcript=transcript,
        )

        validation = self.validator.validate(proposal.action, adapter_name=adapter_name)
        if validation.valid:
            return proposal

        fallback_action = validation.normalized_action or UserAction(
            type=ActionType.send_text,
            text="I need help continuing.",
        )
        fallback_validation = self.validator.validate(fallback_action, adapter_name=adapter_name)
        return ActionProposal(
            action=fallback_validation.normalized_action or fallback_action,
            confidence=min(proposal.confidence, 0.5),
            reason=f"Planner action was not valid: {validation.reason}",
            metadata={"planner": "validator_fallback", "original_reason": proposal.reason},
        )

    def _planner_proposal(
        self,
        *,
        state: ConversationState,
        adapter_name: str,
        scenario: Any,
        persona: Any,
        transcript: list[Any] | None,
    ) -> ActionProposal:
        if self.llm_planner is not None:
            try:
                return self.llm_planner.plan(
                    state=state,
                    adapter_name=adapter_name,
                    scenario=scenario,
                    persona=persona,
                    transcript=transcript,
                )
            except Exception:
                pass
        return self.fallback_planner.plan(
            state=state,
            adapter_name=adapter_name,
            scenario=scenario,
            persona=persona,
            transcript=transcript,
        )
