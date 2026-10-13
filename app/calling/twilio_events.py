"""Twilio event and status mapping helpers."""

from __future__ import annotations

from typing import Any

from app.calling.models import CallEvent, CallEventType, CallProvider, CallStatus


TWILIO_STATUS_MAP: dict[str, CallStatus] = {
    "queued": CallStatus.created,
    "initiated": CallStatus.dialing,
    "ringing": CallStatus.ringing,
    "in-progress": CallStatus.in_progress,
    "completed": CallStatus.completed,
    "busy": CallStatus.busy,
    "failed": CallStatus.failed,
    "no-answer": CallStatus.no_answer,
    "canceled": CallStatus.canceled,
    "cancelled": CallStatus.cancelled,
}


TWILIO_EVENT_MAP: dict[str, CallEventType] = {
    "queued": CallEventType.call_created,
    "initiated": CallEventType.call_started,
    "ringing": CallEventType.call_ringing,
    "in-progress": CallEventType.call_in_progress,
    "completed": CallEventType.call_completed,
    "busy": CallEventType.call_busy,
    "failed": CallEventType.call_failed,
    "no-answer": CallEventType.call_no_answer,
    "canceled": CallEventType.call_cancelled,
    "cancelled": CallEventType.call_cancelled,
}


def map_twilio_status(status: str | None) -> CallStatus:
    """Map a Twilio status string to a generic call status."""
    if status is None:
        return CallStatus.created
    return TWILIO_STATUS_MAP.get(status.strip().lower(), CallStatus.error)


def map_twilio_event_type(status: str | None) -> CallEventType:
    """Map a Twilio status string to a generic call event type."""
    if status is None:
        return CallEventType.custom
    return TWILIO_EVENT_MAP.get(status.strip().lower(), CallEventType.custom)


def twilio_payload_to_event(
    *,
    session_id: str,
    payload: dict[str, Any],
    provider_name: str = "twilio",
) -> CallEvent:
    """Convert a Twilio webhook/status payload into a generic CallEvent."""
    status = payload.get("CallStatus") or payload.get("call_status") or payload.get("status")
    return CallEvent(
        session_id=session_id,
        event_type=map_twilio_event_type(status),
        provider=CallProvider.twilio,
        provider_name=provider_name,
        provider_event_id=payload.get("CallSid") or payload.get("call_sid"),
        provider_metadata={
            "account_sid": payload.get("AccountSid") or payload.get("account_sid"),
            "call_sid": payload.get("CallSid") or payload.get("call_sid"),
            "webhook_payload": dict(payload),
        },
        data={
            "twilio_status": status,
            "status": map_twilio_status(status).value,
        },
    )
