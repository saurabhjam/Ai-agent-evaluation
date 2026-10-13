"""In-memory event publisher for simulated calling lifecycles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.calling.models import CallEvent, CallEventType, CallSession


@dataclass
class CallEventPublisher:
    """Collects call events in memory without threads, webhooks, or IO."""

    events: list[CallEvent] = field(default_factory=list)

    def publish(
        self,
        session: CallSession,
        event_type: CallEventType,
        *,
        provider_event_id: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> CallEvent:
        """Create and store an event for a session."""
        event = CallEvent(
            session_id=session.session_id,
            event_type=event_type,
            provider=session.provider,
            provider_name=session.provider_name,
            provider_event_id=provider_event_id,
            provider_metadata=session.provider_metadata,
            data={
                "status": session.status.value,
                **(data or {}),
            },
        )
        self.events.append(event)
        return event

    def for_session(self, session_id: str) -> list[CallEvent]:
        """Return events for a single call session."""
        return [event for event in self.events if event.session_id == session_id]
