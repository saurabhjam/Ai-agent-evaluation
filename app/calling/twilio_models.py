"""Twilio-specific data models kept inside the calling provider boundary."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class TwilioProviderSettings(BaseModel):
    """Generic config values interpreted by TwilioProvider."""

    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    phone_number: Optional[str] = None
    webhook_secret: Optional[str] = None
    status_callback_url: Optional[str] = None
    voice_url: Optional[str] = None
    timeout_seconds: Optional[float] = None


class TwilioCallPayload(BaseModel):
    """Normalized subset of Twilio call webhook/create payload fields."""

    call_sid: str
    account_sid: Optional[str] = None
    from_number: Optional[str] = Field(default=None, alias="from")
    to_number: Optional[str] = Field(default=None, alias="to")
    call_status: Optional[str] = None
    direction: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class TwilioRecordingPayload(BaseModel):
    """Normalized subset of Twilio recording fields."""

    recording_sid: str
    call_sid: str
    account_sid: Optional[str] = None
    recording_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    channels: int = 1
    format: str = "wav"
    raw: dict[str, Any] = Field(default_factory=dict)
