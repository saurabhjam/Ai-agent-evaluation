"""
Workflow state vocabulary for provider-neutral interaction orchestration.
"""

from __future__ import annotations

from enum import Enum


class WorkflowStatus(str, Enum):
    not_started = "NOT_STARTED"
    started = "STARTED"
    ready = "READY"
    executing = "EXECUTING"
    waiting_response = "WAITING_RESPONSE"
    validating = "VALIDATING"
    retrying = "RETRYING"
    paused = "PAUSED"
    replanning = "REPLANNING"
    completed = "COMPLETED"
    failed = "FAILED"
    cancelled = "CANCELLED"
