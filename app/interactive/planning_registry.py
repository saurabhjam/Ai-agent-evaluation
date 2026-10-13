"""
Registry for pluggable decision planning strategies.
"""

from __future__ import annotations

from typing import Callable

from app.interactive.interaction_plan import InteractionPlan
from app.interactive.planning_context import PlanningContext
from app.interactive.planning_models import (
    DecisionPlannerProtocol,
    PlannerType,
    PlanningStrategyDefinition,
)


PlannerFactory = Callable[[], DecisionPlannerProtocol]


class PlanningRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, PlanningStrategyDefinition] = {}
        self._factories: dict[str, PlannerFactory] = {}

    def register(
        self,
        definition: PlanningStrategyDefinition,
        factory: PlannerFactory,
        *,
        overwrite: bool = False,
    ) -> None:
        name = definition.name.strip()
        if name in self._definitions and not overwrite:
            raise ValueError(f"Planning strategy '{name}' is already registered.")
        self._definitions[name] = definition
        self._factories[name] = factory

    def get_definition(self, name: str) -> PlanningStrategyDefinition:
        normalized = name.strip()
        if normalized not in self._definitions:
            raise KeyError(f"Planning strategy '{normalized}' is not registered.")
        return self._definitions[normalized]

    def create(self, name: str) -> DecisionPlannerProtocol:
        normalized = name.strip()
        if normalized not in self._factories:
            raise KeyError(f"Planning strategy '{normalized}' is not registered.")
        return self._factories[normalized]()

    def list_names(self) -> list[str]:
        return sorted(self._definitions.keys())


def default_planning_registry() -> PlanningRegistry:
    from app.interactive.decision_planner import DefaultDecisionPlanner

    registry = PlanningRegistry()
    registry.register(
        PlanningStrategyDefinition(
            name="default",
            planner_type=PlannerType.default,
            description="Provider-neutral rule-based planner for detected components.",
        ),
        lambda: DefaultDecisionPlanner(),
    )
    return registry
