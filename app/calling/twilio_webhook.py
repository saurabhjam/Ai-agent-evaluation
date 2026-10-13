"""Twilio webhook parsing helpers.

This module does not register FastAPI routes. It only converts Twilio-style
payload dictionaries into provider-neutral event metadata.
"""

from __future__ import annotations

from typing import Any

from app.calling.models import CallEvent
from app.calling.twilio_events import twilio_payload_to_event


def parse_twilio_status_webhook(session_id: str, payload: dict[str, Any]) -> CallEvent:
    """Parse a Twilio status webhook payload into a generic event."""
    return twilio_payload_to_event(session_id=session_id, payload=payload)


def inbound_call_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Return provider metadata for a future inbound Twilio call session."""
    return {
        "account_sid": payload.get("AccountSid"),
        "call_sid": payload.get("CallSid"),
        "from": payload.get("From"),
        "to": payload.get("To"),
        "webhook_payload": dict(payload),
    }
