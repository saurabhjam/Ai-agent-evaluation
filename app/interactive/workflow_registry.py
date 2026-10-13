"""
Registry for pluggable workflow engine implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol

from app.interactive.interaction_plan import InteractionPlan
from app.interactive.workflow_context import WorkflowContext
from app.interactive.workflow_result import WorkflowResult


class WorkflowEngineType(str, Enum):
    default = "default"
    parallel = "parallel"
    ai = "ai"
    custom = "custom"


class WorkflowEngineProtocol(Protocol):
    name: str

    def run(self, plan: InteractionPlan, context: WorkflowContext) -> WorkflowResult:
        """Execute an interaction plan through generic orchestration."""


@dataclass(frozen=True)
class WorkflowEngineDefinition:
    name: str
    engine_type: WorkflowEngineType
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("WorkflowEngineDefinition.name is required.")


WorkflowEngineFactory = Callable[[], WorkflowEngineProtocol]


class WorkflowRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, WorkflowEngineDefinition] = {}
        self._factories: dict[str, WorkflowEngineFactory] = {}

    def register(
        self,
        definition: WorkflowEngineDefinition,
        factory: WorkflowEngineFactory,
        *,
        overwrite: bool = False,
    ) -> None:
        name = definition.name.strip()
        if name in self._definitions and not overwrite:
            raise ValueError(f"Workflow engine '{name}' is already registered.")
        self._definitions[name] = definition
        self._factories[name] = factory

    def get_definition(self, name: str) -> WorkflowEngineDefinition:
        normalized = name.strip()
        if normalized not in self._definitions:
            raise KeyError(f"Workflow engine '{normalized}' is not registered.")
        return self._definitions[normalized]

    def create(self, name: str) -> WorkflowEngineProtocol:
        normalized = name.strip()
        if normalized not in self._factories:
            raise KeyError(f"Workflow engine '{normalized}' is not registered.")
        return self._factories[normalized]()

    def list_names(self) -> list[str]:
        return sorted(self._definitions.keys())


def default_workflow_registry() -> WorkflowRegistry:
    from app.interactive.workflow_engine import DefaultWorkflowEngine

    registry = WorkflowRegistry()
    registry.register(
        WorkflowEngineDefinition(
            name="default",
            engine_type=WorkflowEngineType.default,
            description="Sequential provider-neutral workflow engine.",
        ),
        lambda: DefaultWorkflowEngine(),
    )
    return registry
