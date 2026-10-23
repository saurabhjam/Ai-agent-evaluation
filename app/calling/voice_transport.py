"""EvalForge-side voice transport contracts.

Client provider adapters describe the customer's AI calling agent. Voice
transports describe EvalForge's own PSTN/SIP/WebRTC leg. Keeping these roles
separate lets EvalForge test a Vapi agent through Twilio, a Twilio agent through
LiveKit SIP, or future combinations without changing evaluation logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import json
import time
import uuid
import io
import wave
import logging
import audioop

from app.calling.models import CallDirection, CallProvider, CallSession, CallStatus

logger = logging.getLogger(__name__)


class VoiceTransportError(RuntimeError):
    """Raised when EvalForge cannot establish or operate its call leg."""


@dataclass(frozen=True)
class VoiceTransportCapabilities:
    """Provider-neutral capabilities for EvalForge's side of a call."""

    supports_originate_call: bool = False
    supports_receive_call: bool = False
    supports_audio_send: bool = False
    supports_audio_receive: bool = False
    supports_recording: bool = False


@dataclass(frozen=True)
class VoiceTransportConfig:
    """Runtime configuration for an EvalForge voice transport."""

    transport_name: str
    settings: dict[str, Any] = field(default_factory=dict)
    credentials: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VoiceTransportSession:
    """A real EvalForge call leg created by a transport."""

    transport_name: str
    transport_call_id: str
    direction: CallDirection
    status: CallStatus
    from_number: Optional[str] = None
    to_number: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class VoiceTransport:
    """Base contract for EvalForge-owned PSTN/SIP/WebRTC transports."""

    capabilities = VoiceTransportCapabilities()

    def set_audio_recorder(self, recorder: Any) -> None:
        """Attach an optional passive observer for normalized transport audio."""
        self._audio_recorder = recorder

    def originate_call(
        self,
        *,
        to: str,
        from_: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> VoiceTransportSession:
        raise VoiceTransportError(
            f"Transport '{self.__class__.__name__}' does not support originating calls."
        )

    def allocate_receiver(
        self,
        *,
        metadata: Optional[dict[str, Any]] = None,
    ) -> VoiceTransportSession:
        raise VoiceTransportError(
            f"Transport '{self.__class__.__name__}' does not support receiving calls."
        )

    def hang_up(self, session: VoiceTransportSession) -> None:
        """Best-effort cleanup hook for active transport calls."""

    def connect(self, session: VoiceTransportSession) -> None:
        """Optional hook to connect a media session."""

    def disconnect(self) -> None:
        """Optional hook to disconnect a media session."""

    def last_utterance_complete(self) -> bool:
        """Return whether the most recently received utterance was finalized."""
        return True


class UnconfiguredVoiceTransport(VoiceTransport):
    """Explicit failure transport used when no real EvalForge transport is configured."""

    def __init__(self, reason: str):
        self.reason = reason

    def originate_call(
        self,
        *,
        to: str,
        from_: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> VoiceTransportSession:
        raise VoiceTransportError(self.reason)

    def allocate_receiver(
        self,
        *,
        metadata: Optional[dict[str, Any]] = None,
    ) -> VoiceTransportSession:
        raise VoiceTransportError(self.reason)


class TwilioVoiceTransport(VoiceTransport):
    """EvalForge-owned Twilio transport for originating test calls."""

    capabilities = VoiceTransportCapabilities(
        supports_originate_call=True,
        supports_recording=True,
    )

    def __init__(self, config: VoiceTransportConfig, client: Any = None):
        self.config = config
        self.client = client

    def originate_call(
        self,
        *,
        to: str,
        from_: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> VoiceTransportSession:
        client = self._client()
        settings = self.config.settings or {}
        from_number = from_ or settings.get("from_number") or settings.get("phone_number")
        voice_url = settings.get("voice_url")
        if not from_number:
            raise VoiceTransportError("Twilio voice transport requires from_number.")
        if not voice_url:
            raise VoiceTransportError("Twilio voice transport requires voice_url.")

        call = client.calls.create(
            to=to,
            from_=from_number,
            url=voice_url,
            status_callback=settings.get("status_callback_url"),
            timeout=int(settings["timeout_seconds"]) if settings.get("timeout_seconds") else None,
        )
        call_sid = _get(call, "sid")
        if not call_sid:
            raise VoiceTransportError("Twilio voice transport did not return a call SID.")
        status = _twilio_status(_get(call, "status"))
        return VoiceTransportSession(
            transport_name="twilio",
            transport_call_id=call_sid,
            direction=CallDirection.inbound,
            status=status,
            from_number=from_number,
            to_number=to,
            metadata={
                **(metadata or {}),
                **(self.config.metadata or {}),
                "transport_provider": "twilio",
                "provider_json": _to_dict(call),
            },
        )

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        credentials = self.config.credentials or {}
        account_sid = credentials.get("account_sid")
        auth_token = credentials.get("auth_token")
        if not account_sid or not auth_token:
            raise VoiceTransportError("Twilio voice transport requires account_sid and auth_token.")
        try:
            from twilio.rest import Client
        except ImportError as exc:
            raise VoiceTransportError("Twilio voice transport requires the twilio package.") from exc
        self.client = Client(account_sid, auth_token)
        return self.client


def transport_session_to_call_session(
    session: VoiceTransportSession,
    *,
    provider_name: str,
    provider_call_id: Optional[str] = None,
    provider_metadata: Optional[dict[str, Any]] = None,
) -> CallSession:
    """Represent an EvalForge transport leg in the existing call-session model."""

    return CallSession(
        session_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        direction=session.direction,
        status=session.status,
        from_number=session.from_number,
        to_number=session.to_number,
        provider=CallProvider.custom,
        provider_name=provider_name,
        provider_call_id=provider_call_id,
        provider_metadata={
            "transport_name": session.transport_name,
            "transport_call_id": session.transport_call_id,
            **(provider_metadata or {}),
        },
    )


def _twilio_status(status: Any) -> CallStatus:
    from app.calling.twilio_events import map_twilio_status

    return map_twilio_status(str(status) if status is not None else None)


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

class VapiVoiceTransport(VoiceTransport):
    """EvalForge-owned Vapi WebSocket transport for direct assistant calls."""

    capabilities = VoiceTransportCapabilities(
        supports_originate_call=True,
        supports_audio_send=True,
        supports_audio_receive=True,
        supports_recording=True,
    )

    def __init__(self, config: VoiceTransportConfig, provider: Any = None, websocket_factory: Any = None):
        self.config = config
        self.websocket_factory = websocket_factory
        self.websocket = None
        self.control_messages: list[dict[str, Any]] = []
        self._sent_audio_chunks = 0
        self._received_audio_chunks = 0
        self._last_outgoing_audio_metadata: dict[str, Any] = {}
        self._last_received_utterance_complete = False
        if provider is not None:
            self.provider = provider
        else:
            from app.calling.config import CallingProviderConfig
            from app.calling.providers.vapi import VapiProvider

            provider_config = CallingProviderConfig(
                provider_name="vapi",
                credentials=config.credentials,
                settings=config.settings,
                metadata=config.metadata,
            )
            self.provider = VapiProvider(provider_config)

    def originate_call(
        self,
        *,
        to: str,
        from_: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> VoiceTransportSession:
        logger.info("=== VAPI VOICE TRANSPORT ORIGINATE START ===")
        logger.info("Originating Vapi websocket session")
        logger.info("Transport metadata: %s", metadata or {})
        try:
            call_session = self.provider.create_websocket_call(metadata=metadata)
            websocket_url = call_session.provider_metadata.get("websocket_call_url")
            logger.info("Vapi transport call id: %s", call_session.provider_call_id)
            logger.info("Vapi transport websocket URL: %s", websocket_url)
            return VoiceTransportSession(
                transport_name="vapi",
                transport_call_id=call_session.provider_call_id,
                direction=CallDirection.inbound,
                status=call_session.status,
                from_number=from_,
                to_number=to,
                metadata={
                    **(metadata or {}),
                    **(self.config.metadata or {}),
                    "provider_call_id": call_session.provider_call_id,
                    "transport_provider": "vapi.websocket",
                    "websocket_call_url": call_session.provider_metadata.get("websocket_call_url"),
                    "provider_json": call_session.provider_metadata.get("vapi_response") or {},
                },
            )
        except Exception as e:
            logger.exception("Vapi voice transport failed to originate websocket call")
            raise VoiceTransportError(f"Vapi voice transport failed to originate websocket call: {e}") from e

    def connect(self, session: VoiceTransportSession) -> None:
        logger.info("Opening Vapi WebSocket...")
        websocket_url = session.metadata.get("websocket_call_url")
        logger.info("WebSocket URL: %s", websocket_url)
        if not websocket_url:
            logger.error("Vapi websocket transport session missing websocket_call_url")
            raise VoiceTransportError("Vapi websocket transport session is missing websocket_call_url.")
        factory = self.websocket_factory or _default_websocket_factory()
        self.websocket = factory(websocket_url, timeout=self._timeout_seconds())
        logger.info("WebSocket connected connected=%s", _websocket_connected(self.websocket))

    def send_audio(self, audio_bytes: bytes, turn_index: int = 0) -> None:
        if self.websocket is None:
            logger.error("Cannot send Vapi audio: websocket not connected")
            raise VoiceTransportError("Vapi websocket is not connected.")
        outgoing = self._outgoing_audio(audio_bytes)
        self._sent_audio_chunks += 1
        self._last_outgoing_audio_metadata = self._audio_metadata(audio_bytes, outgoing, turn_index)
        if self._sent_audio_chunks == 1:
            logger.info("Sending first audio chunk")
        logger.info(
            "Sending Vapi audio chunk #%d turn_index=%s input_bytes=%d output_bytes=%d",
            self._sent_audio_chunks,
            turn_index,
            len(audio_bytes),
            len(outgoing),
        )
        _log_websocket_diagnostics(
            self.websocket,
            "before send_audio websocket.send",
            control_messages=self.control_messages,
        )
        if not _websocket_connected(self.websocket):
            logger.error(
                "Vapi websocket closed before sending audio close_status_code=%s close_reason=%s",
                _websocket_close_status(self.websocket),
                _websocket_close_reason(self.websocket),
            )
            raise VoiceTransportError("Vapi websocket is already closed before sending audio.")
        frame_size = self._frame_size_bytes()
        try:
            for frame in _audio_frames(outgoing, frame_size):
                if not _websocket_connected(self.websocket):
                    logger.info(
                        "Vapi websocket closed while streaming audio close_status_code=%s close_reason=%s",
                        _websocket_close_status(self.websocket),
                        _websocket_close_reason(self.websocket),
                    )
                    break
                self.websocket.send(frame, opcode=_binary_opcode())
                self._record_audio("local", frame)
                time.sleep(self._frame_duration_seconds())
        except Exception as exc:
            logger.exception(
                "Vapi websocket send_audio failed close_status_code=%s close_reason=%s",
                _websocket_close_status(self.websocket),
                _websocket_close_reason(self.websocket),
            )
            raise VoiceTransportError(f"Vapi websocket send_audio failed: {exc}") from exc

    def receive_audio(self, timeout_seconds: float = 30.0) -> bytes:
        if self.websocket is None:
            logger.error("Cannot receive Vapi audio: websocket not connected")
            raise VoiceTransportError("Vapi websocket is not connected.")
        logger.info("Waiting for Vapi audio timeout_seconds=%s", timeout_seconds)
        self._last_received_utterance_complete = False
        deadline = time.monotonic() + timeout_seconds
        audio_chunks: list[bytes] = []
        utterance_started = False
        utterance_completed = False
        has_speech = False
        consecutive_silence_seconds = 0.0
        silence_endpoint_seconds = float(self.config.settings.get("silence_endpoint_seconds") or 1.2)
        silence_threshold_rms = float(self.config.settings.get("silence_threshold_rms") or 60.0)
        sample_rate = self._sample_rate()
        bytes_per_second = sample_rate * 2  # 16-bit mono PCM

        while time.monotonic() < deadline:
            _set_timeout(self.websocket, max(deadline - time.monotonic(), 0.1))
            if not _websocket_connected(self.websocket):
                logger.error(
                    "Vapi websocket closed before audio was received close_status_code=%s close_reason=%s",
                    _websocket_close_status(self.websocket),
                    _websocket_close_reason(self.websocket),
                )
                raise VoiceTransportError("Vapi websocket closed before audio was received.")
            try:
                message = self.websocket.recv()
                
                # Log incoming messages for debugging
                if isinstance(message, bytes):
                    logger.debug("Received binary message: length=%d first_32_bytes_hex=%s", len(message), message[:32].hex())
                elif isinstance(message, str):
                    logger.info("Received JSON/text message: %s", message)
                else:
                    logger.info("Received message of type %s: %s", type(message), message)
                    
            except Exception as exc:
                logger.exception(
                    "Vapi websocket receive failed with exception: %s close_status_code=%s close_reason=%s",
                    exc,
                    _websocket_close_status(self.websocket),
                    _websocket_close_reason(self.websocket),
                )
                raise VoiceTransportError(f"Vapi websocket receive failed: {exc}") from exc
                
            if isinstance(message, bytes):
                self._record_audio("remote", message)
                self._received_audio_chunks += 1
                frame_rms = _frame_rms(message)
                frame_duration = len(message) / bytes_per_second if bytes_per_second > 0 else 0.05
                is_silence = frame_rms < silence_threshold_rms

                if not is_silence or utterance_started:
                    has_speech = True
                    consecutive_silence_seconds = 0.0
                    audio_chunks.append(message)
                else:
                    if has_speech:
                        audio_chunks.append(message)
                        consecutive_silence_seconds += frame_duration
                        if utterance_completed or consecutive_silence_seconds >= silence_endpoint_seconds:
                            logger.info(
                                "Received complete Vapi assistant utterance via silence endpointing chunks=%d bytes=%d silence_seconds=%.2f utterance_completed=%s",
                                len(audio_chunks),
                                sum(len(chunk) for chunk in audio_chunks),
                                consecutive_silence_seconds,
                                utterance_completed,
                            )
                            self._last_received_utterance_complete = True
                            return self._incoming_audio(b"".join(audio_chunks))
                    else:
                        # Bounded leading silence (max ~0.5s) to avoid buffering dead air before speech
                        max_leading_chunks = max(int(0.5 / frame_duration), 1) if frame_duration > 0 else 10
                        audio_chunks.append(message)
                        if len(audio_chunks) > max_leading_chunks:
                            audio_chunks.pop(0)
                continue

            if isinstance(message, str):
                control_message = self._record_control_message(message)
                if self._is_assistant_utterance_started(control_message):
                    utterance_started = True
                    has_speech = True
                if self._is_assistant_utterance_completed(control_message):
                    utterance_completed = True
                    if audio_chunks:
                        logger.info(
                            "Received complete Vapi assistant utterance chunks=%d bytes=%d utterance_started=%s",
                            len(audio_chunks),
                            sum(len(chunk) for chunk in audio_chunks),
                            utterance_started,
                        )
                        self._last_received_utterance_complete = True
                        return self._incoming_audio(b"".join(audio_chunks))

        logger.error("Timed out waiting for Vapi websocket audio")
        if audio_chunks and has_speech:
            logger.warning(
                "Timed out waiting for Vapi assistant utterance completion; returning buffered audio chunks=%d bytes=%d",
                len(audio_chunks),
                sum(len(chunk) for chunk in audio_chunks),
            )
            return self._incoming_audio(b"".join(audio_chunks))
        raise TimeoutError("Timed out waiting for Vapi websocket audio.")

    def last_utterance_complete(self) -> bool:
        return self._last_received_utterance_complete

    def hang_up(self, session: VoiceTransportSession) -> None:
        if self.websocket is None:
            logger.info("Vapi hang_up skipped: websocket already disconnected")
            return
        _log_websocket_diagnostics(
            self.websocket,
            "before hang_up websocket.close",
            control_messages=self.control_messages,
        )
        self.disconnect()

    def disconnect(self) -> None:
        if self.websocket is None:
            logger.info("Vapi disconnect skipped: websocket already disconnected")
            return
        try:
            logger.info("Closing Vapi WebSocket")
            self.websocket.close()
            logger.info("Vapi WebSocket closed")
        finally:
            self.websocket = None

    def _record_control_message(self, message: str) -> dict[str, Any]:
        try:
            parsed = json.loads(message)
            if isinstance(parsed, dict):
                self.control_messages.append(parsed)
                logger.info("Received Vapi JSON control frame: %s", parsed)
                logger.info("Stored Vapi control message type=%s", parsed.get("type"))
                return parsed
        except json.JSONDecodeError:
            pass
        parsed = {"type": "unparsed", "message": message}
        self.control_messages.append(parsed)
        logger.info("Stored unparsed Vapi control message")
        return parsed

    def _is_assistant_utterance_started(self, message: dict[str, Any]) -> bool:
        return (
            message.get("type") == "speech-update"
            and message.get("role") in ("assistant", "bot", None)
            and message.get("status") == "started"
        )

    def _is_assistant_utterance_completed(self, message: dict[str, Any]) -> bool:
        msg_type = message.get("type")
        role = message.get("role")
        return (
            msg_type == "speech-update"
            and role in ("assistant", "bot", None)
            and message.get("status") == "stopped"
        )

    def _timeout_seconds(self) -> float:
        value = self.config.settings.get("websocket_timeout_seconds") or self.config.settings.get("timeout_seconds") or 30
        return float(value)

    def _sample_rate(self) -> int:
        audio_format = self.config.settings.get("audio_format") or {}
        return int(audio_format.get("sampleRate") or audio_format.get("sample_rate") or 24000)

    def _frame_duration_seconds(self) -> float:
        value = self.config.settings.get("websocket_frame_duration_ms") or 20
        return max(float(value), 1.0) / 1000.0

    def _frame_size_bytes(self) -> int:
        sample_rate = self._sample_rate()
        samples_per_frame = int(sample_rate * self._frame_duration_seconds())
        return max(samples_per_frame * 2, 2)

    def _outgoing_audio(self, audio_bytes: bytes) -> bytes:
        if _is_wav(audio_bytes):
            return _wav_frames(audio_bytes, target_sample_rate=self._sample_rate())
        return audio_bytes

    def _incoming_audio(self, audio_bytes: bytes) -> bytes:
        if _is_wav(audio_bytes):
            return audio_bytes
        return _pcm_to_wav(audio_bytes, sample_rate=self._sample_rate())

    def _audio_metadata(self, input_bytes: bytes, outgoing: bytes, turn_index: int) -> dict[str, Any]:
        sample_rate = self._sample_rate()
        channels = 1
        bits_per_sample = 16
        if _is_wav(input_bytes):
            try:
                with wave.open(io.BytesIO(input_bytes), "rb") as wav:
                    channels = wav.getnchannels()
                    bits_per_sample = wav.getsampwidth() * 8
            except wave.Error:
                logger.exception("Failed to inspect outgoing WAV metadata; using configured Vapi audio format")
        return {
            "turn_index": turn_index,
            "format": "pcm_s16le",
            "container": "raw",
            "sample_rate": sample_rate,
            "channels": channels,
            "bits_per_sample": bits_per_sample,
            "input_bytes": len(input_bytes),
            "output_bytes": len(outgoing),
            "first_32_bytes_hex": outgoing[:32].hex(),
        }

    def _record_audio(self, direction: str, pcm: bytes) -> None:
        recorder = getattr(self, "_audio_recorder", None)
        if recorder is None:
            return
        try:
            callback = recorder.on_remote_audio if direction == "remote" else recorder.on_local_audio
            callback(
                pcm,
                sample_rate=self._sample_rate(),
                channels=1,
                sample_width=2,
                timestamp=time.monotonic(),
            )
        except Exception:
            logger.exception("EvalForge audio recording failed direction=%s", direction)


def _default_websocket_factory():
    try:
        import websocket
    except ImportError as exc:
        raise VoiceTransportError(
            "Vapi websocket transport requires the 'websocket-client' package."
        ) from exc
    return websocket.create_connection


def _binary_opcode() -> int:
    try:
        import websocket
        return websocket.ABNF.OPCODE_BINARY
    except ImportError:
        logger.info("websocket-client not importable while resolving binary opcode; using RFC opcode 2")
        return 2


def _set_timeout(socket: Any, timeout_seconds: float) -> None:
    if hasattr(socket, "settimeout"):
        socket.settimeout(timeout_seconds)


def _log_websocket_diagnostics(
    socket: Any,
    label: str,
    *,
    control_messages: Optional[list[dict[str, Any]]] = None,
) -> None:
    sock = getattr(socket, "sock", None)
    logger.info(
        (
            "Vapi websocket diagnostics [%s]: websocket.connected=%s "
            "websocket.sock.connected=%s websocket.close_status_code=%s "
            "websocket.close_reason=%s control_messages_count=%s last_control_message=%s"
        ),
        label,
        getattr(socket, "connected", None),
        getattr(sock, "connected", None) if sock is not None else None,
        _websocket_close_status(socket),
        _websocket_close_reason(socket),
        len(control_messages or []),
        (control_messages or [None])[-1],
    )


def _websocket_connected(socket: Any) -> bool:
    connected = getattr(socket, "connected", None)
    if connected is not None:
        return bool(connected)
    closed = getattr(socket, "closed", None)
    if closed is not None:
        return not bool(closed)
    return True


def _websocket_close_status(socket: Any) -> Any:
    for name in ("close_status_code", "close_status", "status", "close_code"):
        value = getattr(socket, name, None)
        if value is not None:
            return value
    sock = getattr(socket, "sock", None)
    if sock is not None:
        for name in ("close_status_code", "close_status", "status", "close_code"):
            value = getattr(sock, name, None)
            if value is not None:
                return value
    return None


def _websocket_close_reason(socket: Any) -> Any:
    for name in ("close_reason", "reason"):
        value = getattr(socket, name, None)
        if value is not None:
            return value
    sock = getattr(socket, "sock", None)
    if sock is not None:
        for name in ("close_reason", "reason"):
            value = getattr(sock, name, None)
            if value is not None:
                return value
    return None


def _frame_rms(frame: bytes) -> float:
    if not frame:
        return 0.0
    if len(frame) % 2 != 0:
        frame = frame[: len(frame) - 1]
    if not frame:
        return 0.0
    try:
        return float(audioop.rms(frame, 2))
    except Exception:
        return 0.0 if not any(frame) else 100.0


def _is_wav(audio_bytes: bytes) -> bool:
    return audio_bytes.startswith(b"RIFF") and b"WAVE" in audio_bytes[:16]


def _audio_frames(audio_bytes: bytes, frame_size: int):
    for start in range(0, len(audio_bytes), frame_size):
        frame = audio_bytes[start : start + frame_size]
        if frame:
            if len(frame) < frame_size:
                frame = frame + (b"\x00" * (frame_size - len(frame)))
            yield frame


def _wav_frames(audio_bytes: bytes, *, target_sample_rate: int) -> bytes:
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    if sample_rate == target_sample_rate:
        return frames
    resampled, _ = audioop.ratecv(frames, sample_width, channels, sample_rate, target_sample_rate, None)
    return resampled


def _pcm_to_wav(audio_bytes: bytes, *, sample_rate: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(audio_bytes)
    return output.getvalue()
