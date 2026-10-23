"""Vapi calling provider."""

from __future__ import annotations

import uuid
import requests
import os
import logging
import time
from datetime import datetime
from typing import Any, Optional

from app.calling.config import CallingProviderConfig
from app.calling.exceptions import ProviderConfigurationError
from app.calling.models import (
    CallArtifactType,
    CallEvent,
    CallProvider,
    CallRecording,
    CallSession,
    CallStatus,
    CallDirection,
    CallTranscriptTurn,
    RawCallTranscript,
    TranscriptSpeaker,
)
from app.calling.provider_adapter import CallProviderAdapter, ProviderCapabilities
from app.calling.providers.vapi_validator import VapiConnectionValidator

logger = logging.getLogger(__name__)


class VapiProvider(CallProviderAdapter):
    """Vapi telephony provider adapter."""

    def __init__(self, config: CallingProviderConfig):
        self.config = config
        self.api_key = self._resolve_secret(config.credentials.get("api_key"))
        self.base_url = str(config.settings.get("base_url") or "https://api.vapi.ai").rstrip("/")

    def get_capabilities(self) -> ProviderCapabilities:
        return VapiConnectionValidator.capabilities()

    def validate_connection(self):
        return VapiConnectionValidator(self.config).validate()

    def create_voice_transport(self):
        from app.calling.voice_transport import VapiVoiceTransport, VoiceTransportConfig

        logger.info("=== VAPI VOICE TRANSPORT CREATE ===")
        logger.info("Creating provider-native Vapi voice transport")
        return VapiVoiceTransport(
            VoiceTransportConfig(
                transport_name="vapi",
                credentials=self.config.credentials,
                settings=self.config.settings,
                metadata=self.config.metadata,
            ),
            provider=self,
        )

    def create_websocket_call(self, metadata: Optional[dict[str, Any]] = None) -> CallSession:
        logger.info("=== VAPI WEBSOCKET CALL CREATE START ===")
        assistant_id = self.config.settings.get("assistant_id")
        logger.info("Validating Vapi API key presence...")
        if not self.api_key:
            logger.error("Vapi API key missing")
            raise ProviderConfigurationError("Vapi provider requires api_key in credentials.")
        logger.info("Vapi API key present: YES")
        logger.info("Assistant ID: %s", assistant_id)
        if not assistant_id:
            logger.error("Vapi assistant_id missing")
            raise ProviderConfigurationError("Vapi provider requires assistant_id in settings.")

        audio_format = self.config.settings.get("audio_format") or {}
        silence_timeout = int(
            self.config.settings.get("silence_timeout_seconds")
            or self.config.settings.get("timeout_seconds")
            or 120
        )
        max_duration = int(
            self.config.settings.get("max_duration_seconds")
            or 600
        )
        payload = {
            "assistantId": assistant_id,
            "assistantOverrides": {
                "silenceTimeoutSeconds": silence_timeout,
                "maxDurationSeconds": max_duration,
            },
            "transport": {
                "provider": "vapi.websocket",
                "audioFormat": {
                    "format": audio_format.get("format") or "pcm_s16le",
                    "container": audio_format.get("container") or "raw",
                    "sampleRate": int(audio_format.get("sampleRate") or audio_format.get("sample_rate") or 24000),
                },
            },
        }

        url = f"{self.base_url}/call"
        logger.info("Creating Vapi call...")
        logger.info("POST /call URL: %s", url)
        logger.info("POST /call payload: %s", payload)
        response = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            timeout=self.config.timeouts.get("request") or self.config.settings.get("timeout_seconds") or 30,
        )
        logger.info("Vapi POST /call HTTP Status: %s", getattr(response, "status_code", "unknown"))
        logger.info("Vapi POST /call HTTP Body: %s", getattr(response, "text", ""))
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            logger.exception("Vapi websocket call creation failed")
            raise RuntimeError(f"Vapi websocket call creation failed: {response.text}") from exc
        body = response.json()
        logger.info("Vapi POST /call JSON keys: %s", list(body.keys()) if isinstance(body, dict) else type(body).__name__)
        call_id = body.get("id")
        websocket_url = (body.get("transport") or {}).get("websocketCallUrl")
        logger.info("Vapi Call ID: %s", call_id)
        logger.info("Vapi WebSocket URL: %s", websocket_url)
        if not call_id:
            logger.error("Vapi websocket call response missing id")
            raise RuntimeError("Vapi websocket call response did not include a call id.")
        if not websocket_url:
            logger.error("Vapi websocket call response missing transport.websocketCallUrl")
            raise RuntimeError("Vapi websocket call response did not include transport.websocketCallUrl.")

        logger.info("=== VAPI WEBSOCKET CALL CREATE SUCCESS ===")
        return CallSession(
            session_id=str(uuid.uuid4()),
            run_id=str(uuid.uuid4()),
            provider=CallProvider.vapi,
            provider_name="vapi",
            direction=CallDirection.inbound,
            status=CallStatus.created,
            provider_call_id=call_id,
            provider_metadata={
                **(metadata or {}),
                "vapi_response": body,
                "websocket_call_url": websocket_url,
                "transport_provider": "vapi.websocket",
            },
        )

    def start_outbound_call(
        self,
        *,
        to: str,
        from_: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CallSession:
        logger.info("Vapi start_outbound_call delegated to direct websocket call")
        return self.create_websocket_call(metadata=metadata)

    def prepare_inbound_call(
        self,
        *,
        expected_from: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CallSession:
        logger.info("Vapi prepare_inbound_call delegated to direct websocket call")
        return self.create_websocket_call(metadata=metadata)

    def get_call_status(self, session: CallSession) -> CallStatus:
        logger.info("Fetching Vapi call status for call_id=%s", session.provider_call_id)
        body = self._fetch_call(session, allow_initial=True)
        status = str(body.get("status") or body.get("endedReason") or "").strip().lower()
        logger.info("Vapi call status raw value: %s", status)
        if status in {"ended", "completed", "finished"}:
            return CallStatus.completed
        if status in {"failed", "error"}:
            return CallStatus.failed
        if status in {"queued", "scheduled"}:
            return CallStatus.created
        if status in {"ringing"}:
            return CallStatus.ringing
        if status in {"in-progress", "in_progress", "active", "started"}:
            return CallStatus.in_progress
        return session.status if session.status != CallStatus.created else CallStatus.in_progress

    @staticmethod
    def is_session_terminal(status: CallStatus) -> bool:
        return status in {
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

    def wait_for_completion(
        self,
        session: CallSession,
        *,
        timeout_seconds: Optional[float] = None,
        poll_interval_seconds: Optional[float] = None,
    ) -> CallSession:
        timeout = float(
            timeout_seconds
            if timeout_seconds is not None
            else self.config.settings.get("completion_timeout_seconds")
            or 60
        )
        interval = float(
            poll_interval_seconds
            if poll_interval_seconds is not None
            else self.config.settings.get("completion_poll_interval_seconds")
            or 1
        )
        deadline = time.monotonic() + timeout
        current = session
        last_body: dict[str, Any] = {}
        while time.monotonic() < deadline:
            body = self._fetch_call(current, allow_initial=False, use_cache=False)
            last_body = body
            status = self._status_from_body(body, fallback=current.status)
            current = self._session_from_body(current, body, status=status)
            logger.info(
                "Vapi completion poll call_id=%s status=%s transcript_ready=%s recording_ready=%s",
                current.provider_call_id,
                status.value,
                bool(_transcript_turns_from_vapi_call(body)),
                _has_vapi_recording(body),
            )
            if self.is_session_terminal(status):
                return current
            time.sleep(max(interval, 0.1))
        if last_body:
            status = self._status_from_body(last_body, fallback=current.status)
            return self._session_from_body(current, last_body, status=CallStatus.timed_out if not self.is_session_terminal(status) else status)
        return current.model_copy(update={"status": CallStatus.timed_out})

    def wait_for_artifacts(
        self,
        session: CallSession,
        *,
        timeout_seconds: Optional[float] = None,
        poll_interval_seconds: Optional[float] = None,
    ) -> CallSession:
        timeout = float(
            timeout_seconds
            if timeout_seconds is not None
            else self.config.settings.get("artifact_timeout_seconds") or 30
        )
        interval = float(
            poll_interval_seconds
            if poll_interval_seconds is not None
            else self.config.settings.get("artifact_poll_interval_seconds") or 1
        )
        deadline = time.monotonic() + timeout
        current = session
        while time.monotonic() < deadline:
            body = self._fetch_call(current, allow_initial=False, use_cache=False)
            status = self._status_from_body(body, fallback=current.status)
            current = self._session_from_body(current, body, status=status)
            if status != CallStatus.completed:
                return current
            if bool(_transcript_turns_from_vapi_call(body)) and _vapi_recording_ready(body):
                return _with_artifact_readiness(current, "ready")
            time.sleep(max(interval, 0.1))
        return _with_artifact_readiness(current, "timed_out")

    def end_call(self, session: CallSession) -> CallSession:
        return session.model_copy(update={"status": CallStatus.completed})

    def fetch_recording(self, session: CallSession) -> Optional[CallRecording]:
        logger.info("Fetching Vapi recording metadata for call_id=%s", session.provider_call_id)
        body = self._fetch_call(session)
        url = _full_call_recording_url(body)
        if not url:
            logger.info("No Vapi recording URL found for call_id=%s", session.provider_call_id)
            return None
        recording_id = body.get("recordingId") or body.get("recording_id") or session.provider_call_id
        return CallRecording(
            session_id=session.session_id,
            provider=CallProvider.vapi,
            provider_name="vapi",
            artifact_type=CallArtifactType.audio,
            recording_id=recording_id,
            provider_recording_id=recording_id,
            remote_url=str(url),
            duration_seconds=_recording_duration(body),
            content_type="audio/wav",
            format="wav",
            metadata={
                "call_id": session.provider_call_id,
                "provider_json": _safe_provider_json(body),
                "alternate_remote_urls": _full_call_recording_urls(body)[1:],
            },
        )

    def fetch_events(self, session: CallSession) -> list[CallEvent]:
        logger.info("Fetching Vapi events for call_id=%s: no event API mapped yet", session.provider_call_id)
        return []

    def fetch_transcript(self, session: CallSession) -> Optional[RawCallTranscript]:
        logger.info("Fetching Vapi transcript for call_id=%s", session.provider_call_id)
        body = self._fetch_call(session)
        turns = _transcript_turns_from_vapi_call(body)
        if not turns:
            logger.info("No Vapi transcript turns found for call_id=%s", session.provider_call_id)
            return None
        logger.info("Vapi transcript turns found: %d", len(turns))
        return RawCallTranscript(
            session_id=session.session_id,
            run_id=session.run_id,
            turns=turns,
            source="provider",
            language=body.get("language"),
            metadata={
                "provider": "vapi",
                "call_id": session.provider_call_id,
                "transcript_source": "vapi_call",
            },
        )

    def download_recording(self, recording: CallRecording, destination_dir: str) -> CallRecording:
        return recording

    @staticmethod
    def _resolve_secret(value: Optional[str]) -> Optional[str]:
        if isinstance(value, str) and value.startswith("env:"):
            env_name = value.split(":", 1)[1].strip()
            return os.getenv(env_name)
        return value

    def _fetch_call(
        self,
        session: CallSession,
        *,
        allow_initial: bool = False,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        logger.info("Vapi _fetch_call start call_id=%s allow_initial=%s", session.provider_call_id, allow_initial)
        cached = session.provider_metadata.get("vapi_response")
        if use_cache and isinstance(cached, dict) and _has_vapi_evidence(cached):
            logger.info("Using cached Vapi call response with evidence")
            return cached
        if use_cache and allow_initial and isinstance(cached, dict) and cached.get("id") and (
            cached.get("status") or cached.get("endedReason")
        ):
            logger.info("Using cached Vapi call response with status")
            return cached
        if not self.api_key:
            logger.error("Cannot fetch Vapi call: API key missing")
            raise ProviderConfigurationError("Vapi provider requires api_key in credentials.")
        if not session.provider_call_id:
            logger.error("Cannot fetch Vapi call: provider_call_id missing")
            raise RuntimeError("Vapi call session is missing provider_call_id.")
        url = f"{self.base_url}/call/{session.provider_call_id}"
        logger.info("GET Vapi call URL: %s", url)
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.config.timeouts.get("request") or self.config.settings.get("timeout_seconds"),
        )
        logger.info("Vapi GET /call HTTP Status: %s", getattr(response, "status_code", "unknown"))
        logger.info("Vapi GET /call HTTP Body: %s", getattr(response, "text", ""))
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            logger.error("Vapi call lookup returned non-object response: %s", type(body).__name__)
            raise RuntimeError("Vapi call lookup returned a non-object response.")
        logger.info("Vapi _fetch_call success keys=%s", list(body.keys()))
        return body

    def _status_from_body(self, body: dict[str, Any], *, fallback: CallStatus) -> CallStatus:
        status = str(body.get("status") or body.get("endedReason") or "").strip().lower()
        if status in {"ended", "completed", "finished"}:
            return CallStatus.completed
        if status in {"failed", "error"}:
            return CallStatus.failed
        if status in {"queued", "scheduled"}:
            return CallStatus.created
        if status in {"ringing"}:
            return CallStatus.ringing
        if status in {"in-progress", "in_progress", "active", "started"}:
            return CallStatus.in_progress
        return fallback if fallback != CallStatus.created else CallStatus.in_progress

    def _session_from_body(
        self,
        session: CallSession,
        body: dict[str, Any],
        *,
        status: CallStatus,
    ) -> CallSession:
        metadata = {
            **(session.provider_metadata or {}),
            "vapi_response": body,
        }
        return session.model_copy(
            update={
                "status": status,
                "started_at": body.get("startedAt") or session.started_at,
                "ended_at": body.get("endedAt") or session.ended_at,
                "provider_metadata": metadata,
            }
        )

def _has_vapi_evidence(data: dict[str, Any]) -> bool:
    return any(
        key in data
        for key in (
            "transcript",
            "messages",
            "recordingUrl",
            "recording_url",
            "stereoRecordingUrl",
            "artifact",
            "status",
        )
    )


def _has_vapi_recording(data: dict[str, Any]) -> bool:
    return bool(_full_call_recording_url(data))


def _full_call_recording_url(data: dict[str, Any]) -> Optional[str]:
    """Resolve Vapi's combined full-call recording inside the provider adapter."""
    urls = _full_call_recording_urls(data)
    return urls[0] if urls else None


def _full_call_recording_urls(data: dict[str, Any]) -> list[str]:
    artifact = data.get("artifact") if isinstance(data.get("artifact"), dict) else {}
    recording = artifact.get("recording") if isinstance(artifact.get("recording"), dict) else {}
    mono = recording.get("mono") if isinstance(recording.get("mono"), dict) else {}
    candidates = (
        mono.get("combinedUrl"),
        mono.get("combined_url"),
        artifact.get("recordingUrl"),
        data.get("recordingUrl"),
        data.get("recording_url"),
        recording.get("stereoUrl"),
        data.get("stereoRecordingUrl"),
    )
    return list(dict.fromkeys(str(value) for value in candidates if value))


def _vapi_recording_ready(data: dict[str, Any]) -> bool:
    for url in _full_call_recording_urls(data):
        try:
            response = requests.get(url, headers={"Range": "bytes=0-0"}, stream=True, timeout=(5, 10))
            try:
                content_type = str(response.headers.get("content-type") or "").lower()
                if response.status_code in {200, 206} and not any(
                    value in content_type for value in ("application/json", "text/html", "text/plain")
                ) and any(response.iter_content(chunk_size=1)):
                    return True
            finally:
                response.close()
        except requests.RequestException:
            continue
    return False


def _with_artifact_readiness(session: CallSession, state: str) -> CallSession:
    metadata = {**(session.provider_metadata or {}), "artifact_readiness": state}
    return session.model_copy(update={"provider_metadata": metadata})


def _recording_duration(data: dict[str, Any]) -> Optional[float]:
    direct = _to_float(data.get("durationSeconds") or data.get("duration") or data.get("endedAtDuration"))
    if direct is not None:
        return direct
    started = data.get("startedAt")
    ended = data.get("endedAt")
    if not started or not ended:
        return None
    try:
        start = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(ended).replace("Z", "+00:00"))
        return max((end - start).total_seconds(), 0.0)
    except (TypeError, ValueError):
        return None


def _transcript_turns_from_vapi_call(data: dict[str, Any]) -> list[CallTranscriptTurn]:
    messages = data.get("messages") or data.get("transcriptMessages")
    if isinstance(messages, list):
        turns: list[CallTranscriptTurn] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            text = _message_text(item)
            if not text:
                continue
            turns.append(
                CallTranscriptTurn(
                    speaker=_message_speaker(item),
                    text=text,
                    turn_index=len(turns),
                    start_time=_to_float(item.get("start") or item.get("startTime")),
                    end_time=_to_float(item.get("end") or item.get("endTime")),
                    metadata={"provider_message": _safe_provider_json(item)},
                )
            )
        if turns:
            return turns

    transcript = data.get("transcript")
    if isinstance(transcript, str) and transcript.strip():
        return _turns_from_transcript_text(transcript)
    return []


def _turns_from_transcript_text(transcript: str) -> list[CallTranscriptTurn]:
    turns: list[CallTranscriptTurn] = []
    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        speaker = TranscriptSpeaker.system
        text = line
        if ":" in line:
            label, text = line.split(":", 1)
            speaker = _speaker(label)
            text = text.strip()
        if text:
            turns.append(CallTranscriptTurn(speaker=speaker, text=text, turn_index=len(turns)))
    return turns


def _message_speaker(item: dict[str, Any]) -> TranscriptSpeaker:
    for key in ("role", "speaker", "sender", "type"):
        value = item.get(key)
        if value:
            return _speaker(value)
    message = item.get("message")
    if isinstance(message, dict):
        return _speaker(message.get("role") or message.get("speaker") or message.get("sender"))
    return TranscriptSpeaker.system


def _message_text(item: dict[str, Any]) -> str:
    candidates: list[str] = []
    for key in ("text", "content", "transcript", "message"):
        value = item.get(key)
        text = _text_from_provider_value(value)
        if text:
            candidates.append(text)

    for text in candidates:
        if not _is_display_label(text):
            return text
    return ""


def _text_from_provider_value(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "content", "transcript", "message"):
            text = _text_from_provider_value(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, list):
        parts = [_text_from_provider_value(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    return str(value).strip()


def _is_display_label(text: str) -> bool:
    return text.strip().lower() in {"you", "user", "customer", "caller", "assistant", "agent", "bot", "ai"}


def _speaker(value: Any) -> TranscriptSpeaker:
    normalized = str(value or "").strip().lower()
    if normalized in {"user", "customer", "caller", "human", "client"}:
        return TranscriptSpeaker.customer
    if normalized in {"assistant", "agent", "bot", "ai"}:
        return TranscriptSpeaker.agent
    return TranscriptSpeaker.system


def _to_float(value: Any) -> Optional[float]:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_provider_json(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    redacted = dict(data)
    for key in list(redacted.keys()):
        if "token" in key.lower() or "key" in key.lower() or "secret" in key.lower():
            redacted[key] = "<redacted>"
    return redacted
