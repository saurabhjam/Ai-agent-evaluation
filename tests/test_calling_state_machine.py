from __future__ import annotations

import pytest

from app.calling.models import CallStatus
from app.calling.state_machine import CallStateMachine, InvalidCallTransitionError


def test_state_machine_allows_happy_path():
    machine = CallStateMachine()

    path = [
        CallStatus.created,
        CallStatus.dialing,
        CallStatus.ringing,
        CallStatus.connected,
        CallStatus.in_progress,
        CallStatus.completed,
    ]

    for current, target in zip(path, path[1:]):
        assert machine.can_transition(current, target)
        assert machine.transition(current, target) == target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (CallStatus.dialing, CallStatus.busy),
        (CallStatus.dialing, CallStatus.no_answer),
        (CallStatus.ringing, CallStatus.timed_out),
        (CallStatus.connected, CallStatus.transferred),
        (CallStatus.in_progress, CallStatus.disconnected),
        (CallStatus.created, CallStatus.cancelled),
        (CallStatus.created, CallStatus.failed),
        (CallStatus.pending, CallStatus.created),
    ],
)
def test_state_machine_valid_alternate_paths(current, target):
    assert CallStateMachine().can_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (CallStatus.created, CallStatus.completed),
        (CallStatus.ringing, CallStatus.in_progress),
        (CallStatus.completed, CallStatus.connected),
        (CallStatus.failed, CallStatus.connected),
        (CallStatus.busy, CallStatus.ringing),
    ],
)
def test_state_machine_rejects_invalid_transitions(current, target):
    machine = CallStateMachine()

    with pytest.raises(InvalidCallTransitionError):
        machine.validate_transition(current, target)


def test_state_machine_terminal_statuses():
    machine = CallStateMachine()

    assert machine.is_terminal(CallStatus.completed)
    assert machine.is_terminal(CallStatus.failed)
    assert not machine.is_terminal(CallStatus.connected)
