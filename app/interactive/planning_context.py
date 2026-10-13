"""
Provider-neutral context for decision planning.

The planner receives scenario and conversation context plus detected
components, then produces a plan. It does not execute interactions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.interactive.component_models import Component
from app.interactive.component_result import ComponentResult


@dataclass
class PlanningContext:
    scenario: Any = None
    components: list[Component] = field(default_factory=list)
    conversation_state: Any = None
    variables: dict[str, Any] = field(default_factory=dict)
    current_step: str | None = None
    previous_result: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_component_result(
        cls,
        result: ComponentResult,
        *,
        scenario: Any = None,
        conversation_state: Any = None,
        variables: dict[str, Any] | None = None,
        current_step: str | None = None,
        previous_result: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> "PlanningContext":
        return cls(
            scenario=scenario,
            components=list(result.components),
            conversation_state=conversation_state,
            variables=variables or {},
            current_step=current_step,
            previous_result=previous_result,
            metadata=metadata or {},
        )
