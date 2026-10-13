"""Twilio recording mapping helpers."""

from __future__ import annotations

from typing import Any

from app.calling.models import CallProvider, CallRecording


def twilio_recording_to_call_recording(
    *,
    session_id: str,
    recording: Any,
    provider_name: str = "twilio",
) -> CallRecording:
    """Convert Twilio recording data into generic recording metadata."""
    sid = _get(recording, "sid") or _get(recording, "recording_sid") or _get(recording, "RecordingSid")
    call_sid = _get(recording, "call_sid") or _get(recording, "CallSid")
    account_sid = _get(recording, "account_sid") or _get(recording, "AccountSid")
    uri = _get(recording, "uri")
    media_url = _get(recording, "media_url") or _get(recording, "recording_url") or _get(recording, "RecordingUrl")
    duration = _get(recording, "duration") or _get(recording, "duration_seconds") or _get(recording, "RecordingDuration")
    channels = _get(recording, "channels") or _get(recording, "Channels") or 1
    duration_seconds = float(duration) if duration not in {None, ""} else None
    return CallRecording(
        session_id=session_id,
        provider=CallProvider.twilio,
        provider_name=provider_name,
        recording_id=sid,
        provider_recording_id=sid,
        remote_url=media_url or uri,
        duration_seconds=duration_seconds,
        channels=int(channels),
        format="wav",
        metadata={
            "call_sid": call_sid,
            "account_sid": account_sid,
            "recording_sid": sid,
            "provider_json": _to_dict(recording),
        },
    )


def _get(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and isinstance(getattr(value, key), (str, int, float, bool, type(None)))
    }
