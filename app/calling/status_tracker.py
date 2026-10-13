"""In-memory status tracker for simulated call sessions."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.calling.models import CallSession, CallStatus


@dataclass
class CallStatusTracker:
    """Stores the latest known session state in memory."""

    sessions: dict[str, CallSession] = field(default_factory=dict)

    def upsert(self, session: CallSession) -> CallSession:
        """Record the latest copy of a session."""
        self.sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> CallSession:
        """Return a tracked session or raise KeyError."""
        return self.sessions[session_id]

    def get_status(self, session_id: str) -> CallStatus:
        """Return the latest tracked status for a session."""
        return self.get_session(session_id).status

    def all_sessions(self) -> list[CallSession]:
        """Return all tracked sessions."""
        return list(self.sessions.values())
