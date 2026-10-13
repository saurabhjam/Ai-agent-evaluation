"""
Result model for universal chatbot interactions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.interactive.interaction_types import InteractionType


@dataclass
class InteractionResult:
    success: bool
    interaction_type: InteractionType
    latency: float = 0.0
    provider_response: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.interaction_type, InteractionType):
            self.interaction_type = InteractionType(self.interaction_type)
        self.latency = max(0.0, float(self.latency))
