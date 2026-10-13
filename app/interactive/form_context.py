"""
Context for universal form understanding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.interactive.component_models import Component
from app.interactive.component_result import ComponentResult


@dataclass
class FormContext:
    components: list[Component] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    scenario: Any = None
    conversation_state: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_component_result(
        cls,
        result: ComponentResult,
        *,
        variables: dict[str, Any] | None = None,
        scenario: Any = None,
        conversation_state: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> "FormContext":
        return cls(
            components=list(result.components),
            variables=variables or {},
            scenario=scenario,
            conversation_state=conversation_state,
            metadata=metadata or {},
        )
