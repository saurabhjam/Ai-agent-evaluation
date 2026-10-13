"""
Shared decision planning models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from app.interactive.interaction_plan import InteractionPlan
from app.interactive.planning_context import PlanningContext


class PlannerType(str, Enum):
    default = "default"
    rule_based = "rule_based"
    ai = "ai"
    custom = "custom"


class DecisionPlannerProtocol(Protocol):
    name: str

    def plan(self, context: PlanningContext) -> InteractionPlan:
        """Create an interaction plan without executing it."""


@dataclass(frozen=True)
class PlanningStrategyDefinition:
    name: str
    planner_type: PlannerType
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("PlanningStrategyDefinition.name is required.")
