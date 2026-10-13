"""Call lifecycle manager for pure in-memory call simulations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.calling.event_publisher import CallEventPublisher
from app.calling.models import (
    CallDirection,
    CallEvent,
    CallEventType,
    CallProvider,
    CallSession,
    CallStatus,
    utc_now_iso,
)
from app.calling.state_machine import CallStateMachine
from app.calling.status_tracker import CallStatusTracker


STATUS_EVENT_MAP: dict[CallStatus, CallEventType] = {
    CallStatus.created: CallEventType.call_created,
    CallStatus.prepared: CallEventType.inbound_prepared,
    CallStatus.dialing: CallEventType.call_started,
    CallStatus.ringing: CallEventType.call_ringing,
    CallStatus.connected: CallEventType.call_connected,
    CallStatus.in_progress: CallEventType.call_in_progress,
    CallStatus.completed: CallEventType.call_completed,
    CallStatus.failed: CallEventType.call_failed,
    CallStatus.busy: CallEventType.call_busy,
    CallStatus.no_answer: CallEventType.call_no_answer,
    CallStatus.canceled: CallEventType.call_cancelled,
    CallStatus.cancelled: CallEventType.call_cancelled,
    CallStatus.timed_out: CallEventType.call_timeout,
    CallStatus.transferred: CallEventType.call_transferred,
    CallStatus.disconnected: CallEventType.call_disconnected,
    CallStatus.error: CallEventType.error,
}


@dataclass
class CallLifecycleManager:
    """Coordinates state transitions, event publication, and status tracking."""

    state_machine: CallStateMachine = field(default_factory=CallStateMachine)
    event_publisher: CallEventPublisher = field(default_factory=CallEventPublisher)
    status_tracker: CallStatusTracker = field(default_factory=CallStatusTracker)

    def create_session(
        self,
        *,
        direction: CallDirection,
        provider: CallProvider = CallProvider.custom,
        provider_name: Optional[str] = "mock",
        provider_call_id: Optional[str] = None,
        scenario_id: Optional[str] = None,
        from_number: Optional[str] = None,
        to_number: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        provider_metadata: Optional[dict[str, Any]] = None,
    ) -> CallSession:
        """Create and track a call session in CREATED state."""
        session = CallSession(
            direction=direction,
            provider=provider,
            provider_name=provider_name,
            provider_call_id=provider_call_id,
            scenario_id=scenario_id,
            from_number=from_number,
            to_number=to_number,
            status=CallStatus.created,
            metadata=metadata or {},
            provider_metadata=provider_metadata or {},
        )
        self.status_tracker.upsert(session)
        self.event_publisher.publish(session, CallEventType.call_created)
        return session

    def transition(
        self,
        session: CallSession,
        target_status: CallStatus,
        *,
        metadata: Optional[dict[str, Any]] = None,
        event_metadata: Optional[dict[str, Any]] = None,
    ) -> tuple[CallSession, CallEvent]:
        """Validate, update, track, and publish a state transition."""
        self.state_machine.validate_transition(session.status, target_status)
        now = utc_now_iso()
        updates: dict[str, Any] = {"status": target_status}
        if metadata:
            updates["metadata"] = {**session.metadata, **metadata}
        if target_status in {CallStatus.dialing, CallStatus.ringing, CallStatus.connected, CallStatus.in_progress}:
            updates["started_at"] = session.started_at or now
        if target_status == CallStatus.connected:
            updates["connected_at"] = session.connected_at or now
        if self.state_machine.is_terminal(target_status) or target_status == CallStatus.disconnected:
            updates["ended_at"] = session.ended_at or now

        updated = session.model_copy(update=updates)
        self.status_tracker.upsert(updated)
        event_type = STATUS_EVENT_MAP.get(target_status, CallEventType.custom)
        event = self.event_publisher.publish(updated, event_type, data=event_metadata)
        return updated, event

    def get_status(self, session_id: str) -> CallStatus:
        """Return the latest status for a tracked session."""
        return self.status_tracker.get_status(session_id)

    def get_events(self, session_id: str) -> list[CallEvent]:
        """Return all events for a session."""
        return self.event_publisher.for_session(session_id)
