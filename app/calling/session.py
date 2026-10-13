"""Session helpers for the isolated calling subsystem."""

from __future__ import annotations

from typing import Any, Optional

from app.calling.models import CallDirection, CallProvider, CallSession, CallStatus, utc_now_iso


def create_call_session(
    *,
    direction: CallDirection,
    provider: CallProvider = CallProvider.custom,
    scenario_id: Optional[str] = None,
    provider_call_id: Optional[str] = None,
    from_number: Optional[str] = None,
    to_number: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> CallSession:
    """Create a vendor-neutral call session."""
    return CallSession(
        direction=direction,
        provider=provider,
        scenario_id=scenario_id,
        provider_call_id=provider_call_id,
        from_number=from_number,
        to_number=to_number,
        metadata=metadata or {},
    )


def transition_call_session(
    session: CallSession,
    status: CallStatus,
    *,
    timestamp: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> CallSession:
    """Return a copy of a session with lifecycle timestamps updated."""
    now = timestamp or utc_now_iso()
    updates: dict[str, Any] = {"status": status}
    if metadata:
        updates["metadata"] = {**session.metadata, **metadata}
    if status in {CallStatus.dialing, CallStatus.ringing, CallStatus.connected}:
        updates["started_at"] = session.started_at or now
    if status == CallStatus.connected:
        updates["connected_at"] = session.connected_at or now
    if status in {CallStatus.completed, CallStatus.failed, CallStatus.canceled, CallStatus.timed_out}:
        updates["ended_at"] = session.ended_at or now
    return session.model_copy(update=updates)
