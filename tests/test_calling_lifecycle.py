from __future__ import annotations

import pytest

from app.calling.lifecycle import CallLifecycleManager
from app.calling.models import CallDirection, CallEventType, CallStatus
from app.calling.state_machine import InvalidCallTransitionError


def test_lifecycle_manager_creates_session_and_event():
    manager = CallLifecycleManager()

    session = manager.create_session(
        direction=CallDirection.outbound,
        from_number="+15550000001",
        to_number="+15550000002",
    )

    assert session.status == CallStatus.created
    assert manager.get_status(session.session_id) == CallStatus.created
    events = manager.get_events(session.session_id)
    assert [event.event_type for event in events] == [CallEventType.call_created]
    assert events[0].provider_name == "mock"


def test_lifecycle_manager_tracks_transitions_and_events():
    manager = CallLifecycleManager()
    session = manager.create_session(direction=CallDirection.outbound)

    session, ringing_event = manager.transition(session, CallStatus.dialing)
    session, connected_event = manager.transition(session, CallStatus.ringing)
    session, progress_event = manager.transition(session, CallStatus.connected)

    assert ringing_event.event_type == CallEventType.call_started
    assert connected_event.event_type == CallEventType.call_ringing
    assert progress_event.event_type == CallEventType.call_connected
    assert manager.get_status(session.session_id) == CallStatus.connected
    assert len(manager.get_events(session.session_id)) == 4


def test_lifecycle_manager_rejects_invalid_transition():
    manager = CallLifecycleManager()
    session = manager.create_session(direction=CallDirection.outbound)

    with pytest.raises(InvalidCallTransitionError):
        manager.transition(session, CallStatus.completed)


def test_lifecycle_manager_records_terminal_timestamp():
    manager = CallLifecycleManager()
    session = manager.create_session(direction=CallDirection.outbound)
    session, _ = manager.transition(session, CallStatus.dialing)
    session, _ = manager.transition(session, CallStatus.busy)

    assert session.status == CallStatus.busy
    assert session.ended_at is not None
    assert manager.get_events(session.session_id)[-1].event_type == CallEventType.call_busy
