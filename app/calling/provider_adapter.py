"""
Provider abstraction for AI Calling Agent Evaluation.

Concrete providers implement this contract in app.calling.providers.*. The core
calling subsystem depends only on this interface and vendor-neutral models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import time
from typing import Any, Optional

from app.calling.models import CallEvent, CallRecording, CallSession, CallStatus, RawCallTranscript


@dataclass(frozen=True)
class ProviderCapabilities:
    """Provider-neutral connection and evidence capabilities."""

    supports_direct_sessions: bool = False
    supports_inbound_sessions: bool = False
    supports_outbound_sessions: bool = False
    supports_webrtc: bool = False
    supports_sip: bool = False
    supports_pstn: bool = False
    requires_external_transport: bool = False
    supports_post_call_transcripts: bool = False
    supports_provider_transcript: bool = False
    preferred_transcript_source: str = "transport"
    supports_live_transcripts: bool = False
    supports_recordings: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def supported_connection_methods(self) -> list[str]:
        methods: list[str] = []
        if self.supports_direct_sessions:
            methods.append("direct_session")
        if self.supports_webrtc:
            methods.append("webrtc")
        if self.supports_sip:
            methods.append("sip")
        if self.supports_pstn:
            methods.append("pstn")
        if self.requires_external_transport:
            methods.append("external_voice_transport")
        return methods


class CallProviderAdapter(ABC):
    """Abstract contract for telephony, SIP, and calling-agent providers."""

    def get_capabilities(self) -> ProviderCapabilities:
        """Return provider-neutral connection and evidence capabilities."""
        return ProviderCapabilities()

    @abstractmethod
    def start_outbound_call(
        self,
        *,
        to: str,
        from_: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CallSession:
        """Start an outbound call and return a vendor-neutral session."""
        ...

    @abstractmethod
    def prepare_inbound_call(
        self,
        *,
        expected_from: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CallSession:
        """Prepare EvalForge to receive and correlate an inbound call."""
        ...

    @abstractmethod
    def get_call_status(self, session: CallSession) -> CallStatus:
        """Return the latest vendor-neutral status for a call session."""
        ...

    def wait_for_completion(
        self,
        session: CallSession,
        *,
        timeout_seconds: float = 10,
        poll_interval_seconds: float = 1,
    ) -> CallSession:
        """Wait for a terminal provider-neutral session status."""
        terminal_statuses = {
            CallStatus.completed,
            CallStatus.failed,
            CallStatus.busy,
            CallStatus.no_answer,
            CallStatus.canceled,
            CallStatus.cancelled,
            CallStatus.timed_out,
            CallStatus.disconnected,
            CallStatus.error,
        }
        deadline = time.monotonic() + timeout_seconds
        current = session
        while time.monotonic() < deadline:
            status = self.get_call_status(current)
            current = current.model_copy(update={"status": status})
            if status in terminal_statuses:
                return current
            time.sleep(max(poll_interval_seconds, 0.1))
        return current.model_copy(update={"status": CallStatus.timed_out})

    @abstractmethod
    def end_call(self, session: CallSession) -> CallSession:
        """End a call and return the updated session."""
        ...

    @abstractmethod
    def fetch_recording(self, session: CallSession) -> Optional[CallRecording]:
        """Return recording metadata if a recording is available."""
        ...

    @abstractmethod
    def fetch_events(self, session: CallSession) -> list[CallEvent]:
        """Return normalized provider events for the session."""
        ...

    def fetch_transcript(self, session: CallSession) -> Optional[RawCallTranscript]:
        """Return a provider transcript when the provider exposes one."""
        return None

    def create_voice_transport(self) -> Optional[Any]:
        """Return a provider-native voice transport when one is available."""
        return None

    @abstractmethod
    def download_recording(self, recording: CallRecording, destination_dir: str) -> CallRecording:
        """Download a recording artifact and return updated metadata."""
        ...
