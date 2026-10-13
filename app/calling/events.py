"""Event helpers for calling-agent evaluation evidence."""

from __future__ import annotations

from typing import Any, Optional

from app.calling.models import CallEvent, CallEventType


def create_call_event(
    *,
    session_id: str,
    event_type: CallEventType,
    provider_event_id: Optional[str] = None,
    data: Optional[dict[str, Any]] = None,
) -> CallEvent:
    """Create a vendor-neutral call event."""
    return CallEvent(
        session_id=session_id,
        event_type=event_type,
        provider_event_id=provider_event_id,
        data=data or {},
    )
