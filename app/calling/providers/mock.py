"""Pure in-memory mock provider for calling lifecycle tests."""

from __future__ import annotations

from typing import Any, Optional
import uuid

from app.calling.lifecycle import CallLifecycleManager
from app.calling.models import (
    CallDirection,
    CallEvent,
    CallProvider,
    CallRecording,
    CallSession,
    CallStatus,
)
from app.calling.provider_adapter import CallProviderAdapter
from app.calling.provider_adapter import ProviderCapabilities


class MockCallProvider(CallProviderAdapter):
    """
    Simulates a telephony provider without IO.

    The provider advances only when its methods are called. It does not create
    threads, timers, webhooks, network calls, recordings, or transcripts.
    """

    def __init__(self, lifecycle_manager: Optional[CallLifecycleManager] = None):
        self.lifecycle_manager = lifecycle_manager or CallLifecycleManager()

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_direct_sessions=True,
            supports_inbound_sessions=True,
            supports_outbound_sessions=True,
            supports_post_call_transcripts=True,
            supports_recordings=True,
            metadata={"simulated": True},
        )

    def start_outbound_call(
        self,
        *,
        to: str,
        from_: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CallSession:
        """Simulate outbound create -> dialing -> ringing -> connected."""
        session = self.lifecycle_manager.create_session(
            direction=CallDirection.outbound,
            provider=CallProvider.custom,
            provider_name="mock",
            provider_call_id=f"mock-call-{uuid.uuid4()}",
            from_number=from_,
            to_number=to,
            metadata=metadata,
            provider_metadata={"simulated": True},
        )
        session, _ = self.lifecycle_manager.transition(session, CallStatus.dialing)
        session, _ = self.lifecycle_manager.transition(session, CallStatus.ringing)
        session, _ = self.lifecycle_manager.transition(session, CallStatus.connected)
        return session

    def prepare_inbound_call(
        self,
        *,
        expected_from: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CallSession:
        """Simulate preparing an inbound call target."""
        session = self.lifecycle_manager.create_session(
            direction=CallDirection.inbound,
            provider=CallProvider.custom,
            provider_name="mock",
            provider_call_id=f"mock-inbound-{uuid.uuid4()}",
            from_number=expected_from,
            metadata=metadata,
            provider_metadata={"simulated": True},
        )
        session, _ = self.lifecycle_manager.transition(session, CallStatus.prepared)
        return session

    def simulate_inbound_connected(self, session: CallSession) -> CallSession:
        """Move a prepared inbound session through ringing -> connected."""
        session, _ = self.lifecycle_manager.transition(session, CallStatus.ringing)
        session, _ = self.lifecycle_manager.transition(session, CallStatus.connected)
        return session

    def simulate_conversation_started(self, session: CallSession) -> CallSession:
        """Move a connected call into in-progress state."""
        session, _ = self.lifecycle_manager.transition(session, CallStatus.in_progress)
        return session

    def simulate_completed(self, session: CallSession) -> CallSession:
        """Complete a connected or in-progress call."""
        if session.status == CallStatus.connected:
            session = self.simulate_conversation_started(session)
        session, _ = self.lifecycle_manager.transition(session, CallStatus.completed)
        return session

    def simulate_failed(self, session: CallSession, reason: str = "mock failure") -> CallSession:
        """Fail a non-terminal call."""
        session, _ = self.lifecycle_manager.transition(
            session,
            CallStatus.failed,
            metadata={"failure_reason": reason},
            event_metadata={"reason": reason},
        )
        return session

    def get_call_status(self, session: CallSession) -> CallStatus:
        """Return the latest tracked status for the session."""
        return self.lifecycle_manager.get_status(session.session_id)

    def end_call(self, session: CallSession) -> CallSession:
        """End a call by completing it when valid."""
        if session.status == CallStatus.completed:
            return session
        return self.simulate_completed(session)

    def fetch_recording(self, session: CallSession) -> Optional[CallRecording]:
        """Return placeholder recording metadata only after completion."""
        latest = self.lifecycle_manager.status_tracker.get_session(session.session_id)
        if latest.status != CallStatus.completed:
            return None
        recording_id = latest.provider_recording_id or f"mock-rec-{latest.session_id}"
        return CallRecording(
            session_id=latest.session_id,
            provider=latest.provider,
            provider_name=latest.provider_name,
            recording_id=recording_id,
            provider_recording_id=recording_id,
            duration_seconds=12.0,
            channels=2,
            format="wav",
            metadata={"placeholder": True},
        )

    def fetch_events(self, session: CallSession) -> list[CallEvent]:
        """Return all events generated for the session."""
        return self.lifecycle_manager.get_events(session.session_id)

    def download_recording(self, recording: CallRecording, destination_dir: str) -> CallRecording:
        """Return placeholder local path metadata without downloading."""
        return recording.model_copy(update={"path": f"{destination_dir}/audio.wav"})
