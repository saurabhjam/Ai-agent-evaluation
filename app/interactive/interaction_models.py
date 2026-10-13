"""
Provider-neutral models for chatbot UI interactions.

Phase 1 only defines the universal model. Provider-specific execution, form
filling, and uploads are intentionally left for later phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.interactive.interaction_types import InteractionType


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


@dataclass
class Interaction:
    type: InteractionType
    label: str
    id: str = field(default_factory=lambda: str(uuid4()))
    selector: str | None = None
    value: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    required: bool = False
    timeout: float | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.type, InteractionType):
            self.type = InteractionType(self.type)

        self.id = self.id.strip() if self.id else ""
        if not self.id:
            raise ValueError("Interaction.id is required.")

        self.label = self.label.strip() if self.label else ""
        if not self.label:
            raise ValueError("Interaction.label is required.")

        self.selector = _strip_optional(self.selector)
        if self.timeout is not None:
            self.timeout = float(self.timeout)
            if self.timeout < 0:
                raise ValueError("Interaction.timeout cannot be negative.")

    def dispatch_value(self) -> Any:
        return self.value if self.value is not None else self.label
