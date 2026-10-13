"""
Structured result returned by the optional interactive runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.interactive.component_models import Component
from app.interactive.form_models import UniversalForm
from app.interactive.interaction_models import Interaction
from app.interactive.workflow_state import WorkflowStatus


@dataclass
class RuntimeResult:
    success: bool
    workflow_status: WorkflowStatus
    interaction_count: int = 0
    completed_interactions: list[Interaction] = field(default_factory=list)
    failed_interactions: list[Interaction] = field(default_factory=list)
    detected_components: list[Component] = field(default_factory=list)
    detected_forms: list[UniversalForm] = field(default_factory=list)
    duration: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.workflow_status, WorkflowStatus):
            self.workflow_status = WorkflowStatus(self.workflow_status)
        self.duration = max(0.0, float(self.duration))
        if self.interaction_count == 0:
            self.interaction_count = len(self.completed_interactions) + len(self.failed_interactions)
