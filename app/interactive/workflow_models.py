"""
Models for universal interaction workflow orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.interactive.interaction_models import Interaction
from app.interactive.workflow_state import WorkflowStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Workflow:
    id: str = field(default_factory=lambda: str(uuid4()))
    status: WorkflowStatus = WorkflowStatus.not_started
    current_step: int = 0
    completed_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)
    retry_count: int = 0
    start_time: datetime | None = None
    end_time: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = self.id.strip() if self.id else ""
        if not self.id:
            raise ValueError("Workflow.id is required.")
        if not isinstance(self.status, WorkflowStatus):
            self.status = WorkflowStatus(self.status)
        if self.current_step < 0:
            raise ValueError("Workflow.current_step cannot be negative.")
        if self.retry_count < 0:
            raise ValueError("Workflow.retry_count cannot be negative.")

    def mark_started(self) -> None:
        self.status = WorkflowStatus.started
        self.start_time = self.start_time or utc_now()

    def mark_completed(self) -> None:
        self.status = WorkflowStatus.completed
        self.end_time = utc_now()

    def mark_failed(self) -> None:
        self.status = WorkflowStatus.failed
        self.end_time = utc_now()


@dataclass
class WorkflowStepRecord:
    interaction: Interaction
    success: bool
    attempt: int = 1
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
