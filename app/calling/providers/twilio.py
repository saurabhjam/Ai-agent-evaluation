"""Twilio Voice provider for AI Calling Agent Evaluation."""

from __future__ import annotations

from typing import Any, Optional
import uuid

from app.calling.config import CallingProviderConfig
from app.calling.exceptions import ProviderConfigurationError, ProviderInitializationError
from app.calling.models import (
    CallDirection,
    CallEvent,
    CallProvider,
    CallRecording,
    CallSession,
    CallStatus,
    CallTranscriptTurn,
    RawCallTranscript,
    TranscriptSpeaker,
)
from app.calling.provider_adapter import CallProviderAdapter, ProviderCapabilities
from app.calling.twilio_events import map_twilio_status, twilio_payload_to_event
from app.calling.twilio_models import TwilioProviderSettings
from app.calling.twilio_recording import twilio_recording_to_call_recording


class TwilioProvider(CallProviderAdapter):
    """Provider adapter for Twilio Voice."""

    def __init__(
        self,
        config: Optional[CallingProviderConfig] = None,
        client: Any = None,
    ):
        self.config = config or CallingProviderConfig(provider_name="twilio")
        self.settings = self._settings_from_config(self.config)
        self.client = client
        self._sessions: dict[str, CallSession] = {}
        self._events: dict[str, list[CallEvent]] = {}
        self._recordings: dict[str, CallRecording] = {}

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_direct_sessions=True,
            supports_inbound_sessions=True,
            supports_outbound_sessions=True,
            supports_pstn=True,
            supports_post_call_transcripts=True,
            supports_recordings=True,
        )

    def start_outbound_call(
        self,
        *,
        to: str,
        from_: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CallSession:
        """Start an outbound Twilio call and return generic session metadata."""
        client = self._client()
        from_number = from_ or self.settings.phone_number
        if not from_number:
            raise ProviderConfigurationError("Twilio provider requires a from phone_number.")

        call = client.calls.create(
            to=to,
            from_=from_number,
            url=self.settings.voice_url,
            status_callback=self.settings.status_callback_url,
            timeout=int(self.settings.timeout_seconds) if self.settings.timeout_seconds else None,
        )
        call_sid = self._get(call, "sid")
        status = map_twilio_status(self._get(call, "status"))
        session = CallSession(
            direction=CallDirection.outbound,
            provider=CallProvider.twilio,
            provider_name="twilio",
            provider_call_id=call_sid,
            from_number=from_number,
            to_number=to,
            status=status,
            metadata=metadata or {},
            provider_metadata={
                "account_sid": self.settings.account_sid,
                "call_sid": call_sid,
                "provider_json": self._to_dict(call),
            },
        )
        self._track(session)
        self._record_event(session, {"CallSid": call_sid, "AccountSid": self.settings.account_sid, "CallStatus": self._get(call, "status")})
        return session

    def prepare_inbound_call(
        self,
        *,
        expected_from: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CallSession:
        """Prepare a provider-neutral inbound Twilio session placeholder."""
        provider_call_id = f"twilio-inbound-{uuid.uuid4()}"
        session = CallSession(
            direction=CallDirection.inbound,
            provider=CallProvider.twilio,
            provider_name="twilio",
            provider_call_id=provider_call_id,
            from_number=expected_from,
            to_number=self.settings.phone_number,
            status=CallStatus.prepared,
            metadata=metadata or {},
            provider_metadata={
                "account_sid": self.settings.account_sid,
                "call_sid": provider_call_id,
                "webhook_secret_configured": bool(self.settings.webhook_secret),
            },
        )
        self._track(session)
        return session

    def get_call_status(self, session: CallSession) -> CallStatus:
        """Fetch or return the latest Twilio call status."""
        if not session.provider_call_id:
            return session.status
        if self.client is None and not self._can_create_client():
            return self._sessions.get(session.session_id, session).status
        call = self._client().calls(session.provider_call_id).fetch()
        status = map_twilio_status(self._get(call, "status"))
        updated = session.model_copy(
            update={
                "status": status,
                "provider_metadata": {
                    **session.provider_metadata,
                    "provider_json": self._to_dict(call),
                },
            }
        )
        self._track(updated)
        return status

    def end_call(self, session: CallSession) -> CallSession:
        """End a Twilio call by requesting completed status."""
        if not session.provider_call_id:
            return session.model_copy(update={"status": CallStatus.completed})
        call = self._client().calls(session.provider_call_id).update(status="completed")
        updated = session.model_copy(
            update={
                "status": map_twilio_status(self._get(call, "status") or "completed"),
                "provider_metadata": {
                    **session.provider_metadata,
                    "provider_json": self._to_dict(call),
                },
            }
        )
        self._track(updated)
        self._record_event(updated, {"CallSid": session.provider_call_id, "AccountSid": self.settings.account_sid, "CallStatus": "completed"})
        return updated

    def fetch_recording(self, session: CallSession) -> Optional[CallRecording]:
        """Return the first Twilio recording metadata for a call, if present."""
        if session.session_id in self._recordings:
            return self._recordings[session.session_id]
        if not session.provider_call_id:
            return None
        recordings = self._client().recordings.list(call_sid=session.provider_call_id, limit=1)
        if not recordings:
            return None
        recording = twilio_recording_to_call_recording(
            session_id=session.session_id,
            recording=recordings[0],
        )
        self._recordings[session.session_id] = recording
        return recording

    def fetch_events(self, session: CallSession) -> list[CallEvent]:
        """Return normalized Twilio events captured by this provider instance."""
        return list(self._events.get(session.session_id, []))

    def fetch_transcript(self, session: CallSession) -> Optional[RawCallTranscript]:
        """Return a Twilio transcription when the account/provider exposes one."""
        if not session.provider_call_id:
            return None
        if not hasattr(self._client(), "transcriptions"):
            return None

        transcriptions = self._client().transcriptions.list(call_sid=session.provider_call_id, limit=20)
        turns: list[CallTranscriptTurn] = []
        for transcription in transcriptions or []:
            text = (
                self._get(transcription, "transcription_text")
                or self._get(transcription, "text")
                or self._get(transcription, "TranscriptionText")
                or ""
            )
            text = str(text).strip()
            if not text:
                continue
            turns.append(
                CallTranscriptTurn(
                    speaker=_speaker_from_twilio_transcription(transcription),
                    text=text,
                    turn_index=len(turns),
                    metadata={
                        "transcription_sid": self._get(transcription, "sid"),
                        "call_sid": session.provider_call_id,
                        "provider_transcription": self._to_dict(transcription),
                    },
                )
            )
        if not turns:
            return None
        return RawCallTranscript(
            session_id=session.session_id,
            run_id=session.run_id,
            turns=turns,
            source="provider",
            metadata={
                "provider": "twilio",
                "call_sid": session.provider_call_id,
                "transcript_source": "twilio_transcriptions",
            },
        )

    def download_recording(self, recording: CallRecording, destination_dir: str) -> CallRecording:
        """Return local path metadata for future recording download support."""
        filename = f"{recording.provider_recording_id or recording.recording_id or recording.artifact_id}.wav"
        return recording.model_copy(update={"path": f"{destination_dir.rstrip('/')}/{filename}"})

    def ingest_status_webhook(self, session: CallSession, payload: dict[str, Any]) -> CallSession:
        """Apply a Twilio status webhook payload to a tracked session."""
        status = map_twilio_status(payload.get("CallStatus") or payload.get("status"))
        updated = session.model_copy(
            update={
                "status": status,
                "provider_metadata": {
                    **session.provider_metadata,
                    "account_sid": payload.get("AccountSid") or session.provider_metadata.get("account_sid"),
                    "call_sid": payload.get("CallSid") or session.provider_call_id,
                    "webhook_payload": dict(payload),
                },
            }
        )
        self._track(updated)
        self._record_event(updated, payload)
        return updated

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        if not self._can_create_client():
            raise ProviderInitializationError(
                "Twilio client requires account_sid, auth_token, and the twilio package."
            )
        from twilio.rest import Client

        self.client = Client(self.settings.account_sid, self.settings.auth_token)
        return self.client

    def _can_create_client(self) -> bool:
        return bool(self.settings.account_sid and self.settings.auth_token)

    def _track(self, session: CallSession) -> None:
        self._sessions[session.session_id] = session

    def _record_event(self, session: CallSession, payload: dict[str, Any]) -> None:
        event = twilio_payload_to_event(session_id=session.session_id, payload=payload)
        self._events.setdefault(session.session_id, []).append(event)

    @staticmethod
    def _settings_from_config(config: CallingProviderConfig) -> TwilioProviderSettings:
        credentials = config.credentials or {}
        settings = config.settings or {}
        return TwilioProviderSettings(
            account_sid=credentials.get("account_sid") or settings.get("account_sid"),
            auth_token=credentials.get("auth_token") or settings.get("auth_token"),
            phone_number=settings.get("phone_number") or credentials.get("phone_number"),
            webhook_secret=credentials.get("webhook_secret") or settings.get("webhook_secret"),
            status_callback_url=settings.get("status_callback_url"),
            voice_url=settings.get("voice_url"),
            timeout_seconds=(config.timeouts or {}).get("call") or settings.get("timeout_seconds"),
        )

    @staticmethod
    def _get(value: Any, name: str) -> Any:
        if isinstance(value, dict):
            return value.get(name)
        return getattr(value, name, None)

    @classmethod
    def _to_dict(cls, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        return {
            key: getattr(value, key)
            for key in dir(value)
            if not key.startswith("_") and isinstance(getattr(value, key), (str, int, float, bool, type(None)))
        }


def _speaker_from_twilio_transcription(transcription: Any) -> TranscriptSpeaker:
    label = ""
    if isinstance(transcription, dict):
        label = str(transcription.get("speaker") or transcription.get("channel") or "")
    else:
        label = str(getattr(transcription, "speaker", "") or getattr(transcription, "channel", ""))
    normalized = label.strip().lower()
    if normalized in {"customer", "caller", "user", "inbound", "0"}:
        return TranscriptSpeaker.customer
    if normalized in {"agent", "assistant", "bot", "outbound", "1"}:
        return TranscriptSpeaker.agent
    return TranscriptSpeaker.system
