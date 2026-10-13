"""Manual configuration for Twilio calling smoke tests."""

from __future__ import annotations

import json
import os
from typing import Optional

from pydantic import BaseModel, Field

from app.calling.config import CallingProviderConfig
from app.calling.models import CallTranscriptTurn, TranscriptSpeaker
from app.schemas import AgentConfig, Persona, TestScenario


class ManualCallingConfig(BaseModel):
    """Config required for a manual Twilio smoke test."""

    twilio_account_sid: str
    twilio_auth_token: str
    from_number: str
    destination_number: str
    scenario: TestScenario
    timeout_seconds: float = 120.0
    poll_interval_seconds: float = 5.0
    recording_enabled: bool = True
    voice_url: Optional[str] = None
    status_callback_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    transcript_turns: list[CallTranscriptTurn] = Field(default_factory=list)
    rag_config: Optional[dict] = None

    def provider_config(self) -> CallingProviderConfig:
        """Build generic provider config for TwilioProvider."""
        return CallingProviderConfig(
            provider_name="twilio",
            credentials={
                "account_sid": self.twilio_account_sid,
                "auth_token": self.twilio_auth_token,
                "webhook_secret": self.webhook_secret,
            },
            settings={
                "phone_number": self.from_number,
                "voice_url": self.voice_url,
                "status_callback_url": self.status_callback_url,
                "recording_enabled": self.recording_enabled,
            },
            timeouts={"call": self.timeout_seconds},
            metadata={"manual_smoke_test": True, **({"rag_config": self.rag_config} if self.rag_config else {})},
        )


def load_manual_calling_config_from_env() -> ManualCallingConfig:
    """Load manual smoke test config from environment variables."""
    transcript_json = os.getenv("CALLING_TRANSCRIPT_JSON", "[]")
    transcript_turns = _parse_transcript_turns(transcript_json)
    rag_config = _parse_optional_dict(os.getenv("CALLING_RAG_CONFIG_JSON"))
    scenario = TestScenario(
        scenario_id=os.getenv("CALLING_SCENARIO_ID", "manual-twilio-calling-smoke"),
        agent=AgentConfig(channel="calling", adapter="twilio"),
        persona=Persona(
            name=os.getenv("CALLING_PERSONA_NAME", "Manual Caller"),
            goal=os.getenv(
                "CALLING_PERSONA_GOAL",
                "Complete a real outbound AI calling agent smoke test",
            ),
            tone=os.getenv("CALLING_PERSONA_TONE", "polite and concise"),
            edge_case=os.getenv("CALLING_PERSONA_EDGE_CASE") or None,
        ),
        rag_context=_parse_optional_list(os.getenv("CALLING_RAG_CONTEXT_JSON")),
    )
    return ManualCallingConfig(
        twilio_account_sid=_required_env("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=_required_env("TWILIO_AUTH_TOKEN"),
        from_number=_required_env("TWILIO_FROM_NUMBER"),
        destination_number=_required_env("CALLING_DESTINATION_NUMBER"),
        scenario=scenario,
        timeout_seconds=float(os.getenv("CALLING_TIMEOUT_SECONDS", "120")),
        poll_interval_seconds=float(os.getenv("CALLING_POLL_INTERVAL_SECONDS", "5")),
        recording_enabled=os.getenv("CALLING_RECORDING_ENABLED", "true").lower() == "true",
        voice_url=os.getenv("TWILIO_VOICE_URL") or None,
        status_callback_url=os.getenv("TWILIO_STATUS_CALLBACK_URL") or None,
        webhook_secret=os.getenv("TWILIO_WEBHOOK_SECRET") or None,
        transcript_turns=transcript_turns,
        rag_config=rag_config,
    )


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _parse_optional_list(value: Optional[str]) -> Optional[list[str]]:
    if not value:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("Expected JSON list.")
    return [str(item) for item in parsed]


def _parse_optional_dict(value: Optional[str]) -> Optional[dict]:
    if not value:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object.")
    return parsed


def _parse_transcript_turns(value: str) -> list[CallTranscriptTurn]:
    raw_turns = json.loads(value)
    if not isinstance(raw_turns, list):
        raise ValueError("CALLING_TRANSCRIPT_JSON must be a JSON list.")
    turns: list[CallTranscriptTurn] = []
    for index, item in enumerate(raw_turns):
        if not isinstance(item, dict):
            raise ValueError("Each transcript turn must be an object.")
        speaker = TranscriptSpeaker(item.get("speaker", "customer"))
        turns.append(
            CallTranscriptTurn(
                speaker=speaker,
                text=str(item.get("text", "")),
                turn_index=int(item.get("turn_index", index)),
                confidence=item.get("confidence"),
                metadata=item.get("metadata") or {},
            )
        )
    return turns
