"""Internal execution events for the calling runtime pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional
import uuid

from pydantic import BaseModel, Field

from app.calling.models import utc_now_iso


class CallingExecutionEventType(str, Enum):
    """Internal lifecycle events for calling execution."""

    started = "started"
    connected = "connected"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    timed_out = "timed_out"


class CallingExecutionEvent(BaseModel):
    """A timestamped internal execution event."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: CallingExecutionEventType
    timestamp: str = Field(default_factory=utc_now_iso)
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
