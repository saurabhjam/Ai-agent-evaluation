"""
Interaction plan model produced by decision planners.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

from app.interactive.interaction_models import Interaction


class PlanStatus(str, Enum):
    planned = "PLANNED"
    empty = "EMPTY"
    failed = "FAILED"


@dataclass
class InteractionPlan:
    ordered_interactions: list[Interaction] = field(default_factory=list)
    reason: str = ""
    confidence: float = 0.0
    status: PlanStatus = PlanStatus.planned
    metadata: dict[str, Any] = field(default_factory=dict)
    next_expected_state: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        self.id = self.id.strip() if self.id else ""
        if not self.id:
            raise ValueError("InteractionPlan.id is required.")
        if not isinstance(self.status, PlanStatus):
            self.status = PlanStatus(self.status)
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        self.ordered_interactions = [
            interaction if isinstance(interaction, Interaction) else Interaction(**interaction)
            for interaction in self.ordered_interactions
        ]

    @property
    def is_actionable(self) -> bool:
        return self.status == PlanStatus.planned and bool(self.ordered_interactions)
