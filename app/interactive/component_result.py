"""
Result model for universal chatbot component detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.interactive.component_models import Component


@dataclass
class ComponentResult:
    success: bool
    components: list[Component] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    provider: str | None = None
    raw_payload: Any = None
    error: str | None = None

    @property
    def component_count(self) -> int:
        return len(self.components)
