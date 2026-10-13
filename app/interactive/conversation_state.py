"""
Conversation state model for future user action planning.

This module is data-only in Phase 1 and does not participate in runtime
execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.interactive.models import NormalizedAgentResponse


@dataclass
class ConversationState:
    scenario_id: Optional[str] = None
    current_goal: str = ""
    completed_goals: list[str] = field(default_factory=list)
    pending_goals: list[str] = field(default_factory=list)
    known_facts: dict[str, Any] = field(default_factory=dict)
    missing_facts: list[str] = field(default_factory=list)
    conversation_memory: list[str] = field(default_factory=list)
    current_agent_response: NormalizedAgentResponse = field(default_factory=NormalizedAgentResponse)
    available_actions: list[str] = field(default_factory=list)
    planner_context: dict[str, Any] = field(default_factory=dict)
    transcript: list[Any] = field(default_factory=list)


class ConversationStateBuilder:
    """Build a planner-friendly state object from generic inputs."""

    def build(
        self,
        *,
        scenario_id: Optional[str] = None,
        persona_goal: str = "",
        transcript: Optional[list[Any]] = None,
        current_agent_response: Optional[NormalizedAgentResponse] = None,
        known_facts: Optional[dict[str, Any]] = None,
        missing_facts: Optional[list[str]] = None,
        planner_context: Optional[dict[str, Any]] = None,
    ) -> ConversationState:
        response = current_agent_response or NormalizedAgentResponse()
        available_actions = [
            element.action_value()
            for element in response.interactive
        ]
        return ConversationState(
            scenario_id=scenario_id,
            current_goal=persona_goal,
            pending_goals=[persona_goal] if persona_goal else [],
            known_facts=known_facts or {},
            missing_facts=missing_facts or [],
            current_agent_response=response,
            available_actions=available_actions,
            planner_context=planner_context or {},
            transcript=transcript or [],
        )
