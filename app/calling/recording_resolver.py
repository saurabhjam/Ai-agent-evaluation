"""Resolve provider webhook payloads into recording metadata."""

from __future__ import annotations

from typing import Any

from app.calling.models import CallRecording, CallSession
from app.calling.twilio_recording import twilio_recording_to_call_recording


class RecordingResolver:
    """Provider-aware resolver that returns generic CallRecording metadata."""

    def resolve(
        self,
        *,
        provider_name: str,
        session: CallSession,
        payload: dict[str, Any],
    ) -> CallRecording | None:
        """Resolve recording metadata from provider payload."""
        normalized_provider = provider_name.strip().lower()
        if normalized_provider == "twilio":
            recording_sid = payload.get("RecordingSid") or payload.get("recording_sid")
            recording_url = payload.get("RecordingUrl") or payload.get("recording_url")
            if not recording_sid and not recording_url:
                return None
            return twilio_recording_to_call_recording(
                session_id=session.session_id,
                recording={
                    "RecordingSid": recording_sid,
                    "CallSid": payload.get("CallSid") or payload.get("call_sid") or session.provider_call_id,
                    "AccountSid": payload.get("AccountSid") or payload.get("account_sid"),
                    "RecordingUrl": recording_url,
                    "RecordingDuration": payload.get("RecordingDuration") or payload.get("duration"),
                    "Channels": payload.get("Channels") or payload.get("channels") or 1,
                    **payload,
                },
            )
        return None
