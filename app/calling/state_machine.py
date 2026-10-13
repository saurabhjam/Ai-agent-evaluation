"""Validated call lifecycle state machine for the calling subsystem."""

from __future__ import annotations

from dataclasses import dataclass

from app.calling.models import CallStatus


class InvalidCallTransitionError(ValueError):
    """Raised when a call attempts an invalid lifecycle transition."""


VALID_CALL_TRANSITIONS: dict[CallStatus, set[CallStatus]] = {
    CallStatus.created: {
        CallStatus.dialing,
        CallStatus.prepared,
        CallStatus.cancelled,
        CallStatus.canceled,
        CallStatus.failed,
        CallStatus.error,
    },
    CallStatus.pending: {
        CallStatus.created,
        CallStatus.prepared,
        CallStatus.dialing,
        CallStatus.cancelled,
        CallStatus.canceled,
        CallStatus.failed,
        CallStatus.error,
    },
    CallStatus.prepared: {
        CallStatus.ringing,
        CallStatus.connected,
        CallStatus.timed_out,
        CallStatus.no_answer,
        CallStatus.cancelled,
        CallStatus.canceled,
        CallStatus.failed,
        CallStatus.error,
    },
    CallStatus.dialing: {
        CallStatus.ringing,
        CallStatus.busy,
        CallStatus.no_answer,
        CallStatus.cancelled,
        CallStatus.canceled,
        CallStatus.failed,
        CallStatus.timed_out,
        CallStatus.error,
    },
    CallStatus.ringing: {
        CallStatus.connected,
        CallStatus.busy,
        CallStatus.no_answer,
        CallStatus.cancelled,
        CallStatus.canceled,
        CallStatus.failed,
        CallStatus.timed_out,
        CallStatus.error,
    },
    CallStatus.connected: {
        CallStatus.in_progress,
        CallStatus.transferred,
        CallStatus.disconnected,
        CallStatus.completed,
        CallStatus.failed,
        CallStatus.error,
    },
    CallStatus.in_progress: {
        CallStatus.completed,
        CallStatus.transferred,
        CallStatus.disconnected,
        CallStatus.failed,
        CallStatus.error,
    },
    CallStatus.transferred: {
        CallStatus.completed,
        CallStatus.disconnected,
        CallStatus.failed,
        CallStatus.error,
    },
    CallStatus.disconnected: {CallStatus.completed, CallStatus.failed, CallStatus.error},
    CallStatus.busy: set(),
    CallStatus.no_answer: set(),
    CallStatus.completed: set(),
    CallStatus.failed: set(),
    CallStatus.canceled: set(),
    CallStatus.cancelled: set(),
    CallStatus.timed_out: set(),
    CallStatus.error: set(),
}


TERMINAL_CALL_STATUSES: set[CallStatus] = {
    CallStatus.busy,
    CallStatus.no_answer,
    CallStatus.completed,
    CallStatus.failed,
    CallStatus.canceled,
    CallStatus.cancelled,
    CallStatus.timed_out,
    CallStatus.error,
}


@dataclass(frozen=True)
class CallStateMachine:
    """Pure state transition validator for call sessions."""

    transitions: dict[CallStatus, set[CallStatus]] | None = None

    def allowed_next_states(self, status: CallStatus) -> set[CallStatus]:
        """Return allowed destination states from the current status."""
        return set(self._transitions().get(status, set()))

    def can_transition(self, current: CallStatus, target: CallStatus) -> bool:
        """Return whether current can move to target."""
        return target in self.allowed_next_states(current)

    def validate_transition(self, current: CallStatus, target: CallStatus) -> None:
        """Raise when a transition is not allowed."""
        if not self.can_transition(current, target):
            raise InvalidCallTransitionError(
                f"Invalid call transition: {current.value} -> {target.value}"
            )

    def transition(self, current: CallStatus, target: CallStatus) -> CallStatus:
        """Validate and return the target status."""
        self.validate_transition(current, target)
        return target

    def is_terminal(self, status: CallStatus) -> bool:
        """Return whether a state is terminal."""
        return status in TERMINAL_CALL_STATUSES

    def _transitions(self) -> dict[CallStatus, set[CallStatus]]:
        return self.transitions or VALID_CALL_TRANSITIONS
