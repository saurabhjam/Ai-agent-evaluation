"""Provider-neutral webhook dispatch and ingestion layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.calling.evidence_builder import EvidenceBuilder
from app.calling.models import CallEvent, CallEventType, CallRecording, CallSession, CallStatus
from app.calling.recording_ingestion import RecordingIngestionService
from app.calling.webhook_models import WebhookIngestionResult


class ProviderWebhookHandler(Protocol):
    """Provider-specific webhook handler contract."""

    provider_name: str

    def event_key(self, payload: dict[str, Any]) -> str:
        """Return an idempotency key for a provider webhook payload."""
        ...

    def apply(self, session: CallSession, payload: dict[str, Any]) -> tuple[CallSession, CallEvent | None]:
        """Apply payload to a session and return updated session plus event."""
        ...


@dataclass
class WebhookHandler:
    """Generic dispatcher for provider webhook payloads."""

    provider_handlers: dict[str, ProviderWebhookHandler] = field(default_factory=dict)
    recording_ingestion: RecordingIngestionService = field(default_factory=RecordingIngestionService)
    evidence_builder: EvidenceBuilder = field(default_factory=EvidenceBuilder)
    _processed_keys: set[str] = field(default_factory=set)

    def register(self, handler: ProviderWebhookHandler) -> None:
        """Register a provider-specific webhook handler."""
        self.provider_handlers[handler.provider_name.lower()] = handler

    def handle(
        self,
        *,
        provider_name: str,
        session: CallSession,
        payload: dict[str, Any],
    ) -> WebhookIngestionResult:
        """Process a provider webhook idempotently."""
        normalized_provider = provider_name.strip().lower()
        if normalized_provider not in self.provider_handlers:
            raise ValueError(f"No webhook handler registered for provider '{provider_name}'.")
        handler = self.provider_handlers[normalized_provider]
        key = f"{normalized_provider}:{session.session_id}:{handler.event_key(payload)}"
        if key in self._processed_keys:
            return WebhookIngestionResult(
                provider_name=normalized_provider,
                session=session,
                duplicate=True,
                ignored=True,
                metadata={"idempotency_key": key},
            )
        self._processed_keys.add(key)

        updated_session, event = handler.apply(session, payload)
        recording = self.recording_ingestion.ingest(
            provider_name=normalized_provider,
            session=updated_session,
            payload=payload,
        )
        recordings = [recording] if recording else []
        events = [event] if event else []
        evidence = self.evidence_builder.build(
            session=updated_session,
            events=events,
            recordings=recordings,
            transcript=None,
            artifacts=[],
            rag_context=None,
        )
        return WebhookIngestionResult(
            provider_name=normalized_provider,
            session=updated_session,
            event=event,
            recording=recording,
            conversation_evidence=evidence,
            metadata={"idempotency_key": key},
        )


@dataclass(frozen=True)
class TwilioWebhookHandler:
    """Twilio-specific webhook handler."""

    provider_name: str = "twilio"

    def event_key(self, payload: dict[str, Any]) -> str:
        """Return a stable idempotency key for Twilio callbacks."""
        return ":".join(
            [
                str(payload.get("CallSid") or payload.get("call_sid") or "unknown-call"),
                str(payload.get("RecordingSid") or payload.get("recording_sid") or "no-recording"),
                str(payload.get("CallStatus") or payload.get("RecordingStatus") or payload.get("status") or "unknown-status"),
            ]
        )

    def apply(self, session: CallSession, payload: dict[str, Any]) -> tuple[CallSession, CallEvent | None]:
        """Map Twilio status/recording callbacks onto generic session/event models."""
        from app.calling.twilio_events import map_twilio_status, twilio_payload_to_event

        status_value = payload.get("CallStatus") or payload.get("status")
        recording_status = payload.get("RecordingStatus") or payload.get("recording_status")
        status = map_twilio_status(status_value)
        if recording_status and status == CallStatus.created:
            status = session.status
        provider_metadata = {
            **session.provider_metadata,
            "account_sid": payload.get("AccountSid") or session.provider_metadata.get("account_sid"),
            "call_sid": payload.get("CallSid") or session.provider_call_id,
            "webhook_payload": dict(payload),
        }
        if payload.get("RecordingSid"):
            provider_metadata["recording_sid"] = payload.get("RecordingSid")
        updated = session.model_copy(
            update={
                "status": status,
                "provider_metadata": provider_metadata,
                "provider_recording_id": payload.get("RecordingSid") or session.provider_recording_id,
            }
        )
        event_payload = dict(payload)
        if recording_status and not status_value:
            event_payload["CallStatus"] = (
                "completed" if recording_status in {"completed", "recording-completed"} else "in-progress"
            )
        event = twilio_payload_to_event(session_id=session.session_id, payload=event_payload)
        if recording_status in {"completed", "recording-completed", "available", "recording-available"}:
            event = event.model_copy(update={"event_type": CallEventType.recording_available})
        return updated, event
