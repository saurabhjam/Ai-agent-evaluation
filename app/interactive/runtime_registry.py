"""
Registry for optional interactive runtime implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol

from app.interactive.runtime_context import RuntimeContext
from app.interactive.runtime_result import RuntimeResult


class RuntimeType(str, Enum):
    default = "default"
    custom = "custom"


class InteractiveRuntimeProtocol(Protocol):
    name: str

    def run(self, context: RuntimeContext) -> RuntimeResult:
        """Run the provider-neutral interactive pipeline."""


@dataclass(frozen=True)
class RuntimeDefinition:
    name: str
    runtime_type: RuntimeType
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("RuntimeDefinition.name is required.")


RuntimeFactory = Callable[[], InteractiveRuntimeProtocol]


class RuntimeRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, RuntimeDefinition] = {}
        self._factories: dict[str, RuntimeFactory] = {}

    def register(self, definition: RuntimeDefinition, factory: RuntimeFactory, *, overwrite: bool = False) -> None:
        name = definition.name.strip()
        if name in self._definitions and not overwrite:
            raise ValueError(f"Interactive runtime '{name}' is already registered.")
        self._definitions[name] = definition
        self._factories[name] = factory

    def create(self, name: str) -> InteractiveRuntimeProtocol:
        normalized = name.strip()
        if normalized not in self._factories:
            raise KeyError(f"Interactive runtime '{normalized}' is not registered.")
        return self._factories[normalized]()

    def list_names(self) -> list[str]:
        return sorted(self._definitions.keys())


def default_runtime_registry() -> RuntimeRegistry:
    from app.interactive.interactive_runtime import InteractiveRuntime

    registry = RuntimeRegistry()
    registry.register(
        RuntimeDefinition(
            name="default",
            runtime_type=RuntimeType.default,
            description="Provider-neutral interactive chatbot runtime.",
        ),
        lambda: InteractiveRuntime(),
    )
    return registry
