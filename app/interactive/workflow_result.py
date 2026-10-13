"""
Result model for workflow orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.interactive.interaction_models import Interaction
from app.interactive.workflow_state import WorkflowStatus


@dataclass
class WorkflowResult:
    success: bool
    status: WorkflowStatus
    completed_interactions: list[Interaction] = field(default_factory=list)
    failed_interactions: list[Interaction] = field(default_factory=list)
    duration: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, WorkflowStatus):
            self.status = WorkflowStatus(self.status)
        self.duration = max(0.0, float(self.duration))
