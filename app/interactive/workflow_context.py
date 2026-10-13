"""
Context for executing an InteractionPlan through a workflow engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.interactive.interaction_context import InteractionContext
from app.interactive.interaction_executor import InteractionExecutor


@dataclass
class WorkflowContext:
    interaction_context: InteractionContext
    interaction_executor: InteractionExecutor
    max_retries: int = 0
    timeout_seconds: float | None = None
    wait_after_step_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("WorkflowContext.max_retries cannot be negative.")
        if self.timeout_seconds is not None and self.timeout_seconds < 0:
            raise ValueError("WorkflowContext.timeout_seconds cannot be negative.")
        if self.wait_after_step_seconds < 0:
            raise ValueError("WorkflowContext.wait_after_step_seconds cannot be negative.")
