"""
Registry for pluggable form engine implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol

from app.interactive.form_context import FormContext
from app.interactive.form_result import FormResult


class FormEngineType(str, Enum):
    default = "default"
    ai = "ai"
    custom = "custom"


class FormEngineProtocol(Protocol):
    name: str

    def understand(self, context: FormContext) -> FormResult:
        """Return universal forms detected from chatbot components."""


@dataclass(frozen=True)
class FormEngineDefinition:
    name: str
    engine_type: FormEngineType
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("FormEngineDefinition.name is required.")


FormEngineFactory = Callable[[], FormEngineProtocol]


class FormRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, FormEngineDefinition] = {}
        self._factories: dict[str, FormEngineFactory] = {}

    def register(self, definition: FormEngineDefinition, factory: FormEngineFactory, *, overwrite: bool = False) -> None:
        name = definition.name.strip()
        if name in self._definitions and not overwrite:
            raise ValueError(f"Form engine '{name}' is already registered.")
        self._definitions[name] = definition
        self._factories[name] = factory

    def create(self, name: str) -> FormEngineProtocol:
        normalized = name.strip()
        if normalized not in self._factories:
            raise KeyError(f"Form engine '{normalized}' is not registered.")
        return self._factories[normalized]()

    def list_names(self) -> list[str]:
        return sorted(self._definitions.keys())


def default_form_registry() -> FormRegistry:
    from app.interactive.form_engine import DefaultFormEngine

    registry = FormRegistry()
    registry.register(
        FormEngineDefinition(
            name="default",
            engine_type=FormEngineType.default,
            description="Provider-neutral form understanding engine.",
        ),
        lambda: DefaultFormEngine(),
    )
    return registry
