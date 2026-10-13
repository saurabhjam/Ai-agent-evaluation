from __future__ import annotations

import json
import io
import wave
from unittest.mock import patch

from app.calling.config import CallingProviderConfig
from app.calling.models import CallDirection
from app.calling.providers.vapi import VapiProvider
from app.calling.providers.vapi_validator import VapiConnectionValidator
from app.calling.voice_transport import VapiVoiceTransport, VoiceTransportConfig, VoiceTransportError


class Response:
    def __init__(self, body):
        self.body = body
        self.text = json.dumps(body)

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


def test_vapi_validator_checks_assistant_and_returns_websocket_capabilities(monkeypatch):
    captured = {}

    def get(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        return Response({"id": "assistant-1"})

    monkeypatch.setattr("app.calling.providers.vapi_validator.requests.get", get)

    result = VapiConnectionValidator(
        CallingProviderConfig(
            provider_name="vapi",
            credentials={"api_key": "test-key"},
            settings={"assistant_id": "assistant-1"},
        )
    ).validate()

    assert result.success is True
    assert result.capabilities.supports_direct_sessions is True
    assert result.capabilities.supports_live_transcripts is True
    assert result.capabilities.requires_external_transport is False
    assert captured["url"].endswith("/assistant/assistant-1")
    assert captured["headers"]["Authorization"] == "Bearer test-key"


def test_vapi_provider_creates_official_websocket_call(monkeypatch):
    captured = {}

    def post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return Response(
            {
                "id": "call-1",
                "transport": {"websocketCallUrl": "wss://example.test/call-1"},
            }
        )

    monkeypatch.setattr("app.calling.providers.vapi.requests.post", post)

    provider = VapiProvider(
        CallingProviderConfig(
            provider_name="vapi",
            credentials={"api_key": "test-key"},
            settings={"assistant_id": "assistant-1"},
        )
    )
    session = provider.create_websocket_call(metadata={"scenario_id": "scenario-1"})

    assert session.direction == CallDirection.inbound
    assert session.provider_call_id == "call-1"
    assert session.provider_metadata["websocket_call_url"] == "wss://example.test/call-1"
    assert captured["json"]["assistantId"] == "assistant-1"
    assert captured["json"]["transport"]["provider"] == "vapi.websocket"
    assert captured["json"]["transport"]["audioFormat"]["format"] == "pcm_s16le"
    assert captured["json"]["transport"]["audioFormat"]["container"] == "raw"
    assert captured["json"]["transport"]["audioFormat"]["sampleRate"] == 24000


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.timeout = None
        self.messages = [json.dumps({"type": "status", "status": "connected"}), b"\x00\x00\x01\x00"]
        self.closed = False

    def send(self, payload, opcode=None):
        self.sent.append((payload, opcode))

    def recv(self):
        return self.messages.pop(0)

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        self.closed = True


class ClosedFakeSocket(FakeSocket):
    def __init__(self):
        super().__init__()
        self.closed = True
        self.close_status = 1008
        self.close_reason = "Unsupported audio format"


class ClosingAfterFirstSendSocket(FakeSocket):
    def send(self, payload, opcode=None):
        super().send(payload, opcode=opcode)
        self.closed = True


def _wav_bytes(sample_rate: int, duration_seconds: float = 0.04) -> bytes:
    frames = b"\x00\x00" * int(sample_rate * duration_seconds)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)
    return buf.getvalue()


def test_vapi_voice_transport_connects_sends_receives_and_ends_call():
    socket = FakeSocket()
    transport = VapiVoiceTransport(
        VoiceTransportConfig(
            transport_name="vapi",
            settings={"assistant_id": "assistant-1"},
            credentials={"api_key": "test-key"},
        ),
        websocket_factory=lambda url, timeout: socket,
    )
    session = type(
        "Session",
        (),
        {
            "metadata": {"websocket_call_url": "wss://example.test/call-1"},
        },
    )()

    transport.connect(session)
    transport.send_audio(b"\x00\x00", turn_index=0)
    audio = transport.receive_audio(timeout_seconds=1)
    transport.hang_up(session)

    assert socket.sent[0][1] == 2
    assert audio.startswith(b"RIFF")
    assert transport.control_messages[0]["type"] == "status"
    assert len(socket.sent) == 1
    assert socket.closed is True


def test_vapi_voice_transport_streams_audio_in_realtime_frames():
    socket = FakeSocket()
    transport = VapiVoiceTransport(
        VoiceTransportConfig(
            transport_name="vapi",
            settings={
                "assistant_id": "assistant-1",
                "audio_format": {"sampleRate": 24000},
                "websocket_frame_duration_ms": 20,
            },
            credentials={"api_key": "test-key"},
        ),
        websocket_factory=lambda url, timeout: socket,
    )
    session = type(
        "Session",
        (),
        {
            "metadata": {"websocket_call_url": "wss://example.test/call-1"},
        },
    )()

    transport.connect(session)
    with patch("app.calling.voice_transport.time.sleep") as sleep:
        transport.send_audio(b"\x00" * 1920, turn_index=0)

    assert [len(payload) for payload, _ in socket.sent] == [960, 960]
    assert all(opcode == 2 for _, opcode in socket.sent)
    assert sleep.call_count == 2


def test_vapi_voice_transport_resamples_wav_to_negotiated_sample_rate():
    socket = FakeSocket()
    transport = VapiVoiceTransport(
        VoiceTransportConfig(
            transport_name="vapi",
            settings={
                "assistant_id": "assistant-1",
                "audio_format": {"sampleRate": 24000},
                "websocket_frame_duration_ms": 20,
            },
            credentials={"api_key": "test-key"},
        ),
        websocket_factory=lambda url, timeout: socket,
    )
    session = type(
        "Session",
        (),
        {
            "metadata": {"websocket_call_url": "wss://example.test/call-1"},
        },
    )()

    transport.connect(session)
    with patch("app.calling.voice_transport.time.sleep"):
        transport.send_audio(_wav_bytes(22050), turn_index=0)

    assert [len(payload) for payload, _ in socket.sent] == [960, 960]
    assert transport._last_outgoing_audio_metadata["sample_rate"] == 24000


def test_vapi_voice_transport_stops_streaming_when_socket_closes():
    socket = ClosingAfterFirstSendSocket()
    transport = VapiVoiceTransport(
        VoiceTransportConfig(
            transport_name="vapi",
            settings={
                "assistant_id": "assistant-1",
                "audio_format": {"sampleRate": 24000},
                "websocket_frame_duration_ms": 20,
            },
            credentials={"api_key": "test-key"},
        ),
        websocket_factory=lambda url, timeout: socket,
    )
    session = type(
        "Session",
        (),
        {
            "metadata": {"websocket_call_url": "wss://example.test/call-1"},
        },
    )()

    transport.connect(session)
    with patch("app.calling.voice_transport.time.sleep"):
        transport.send_audio(b"\x00" * 2880, turn_index=0)

    assert len(socket.sent) == 1


def test_vapi_voice_transport_does_not_send_to_closed_socket():
    socket = ClosedFakeSocket()
    transport = VapiVoiceTransport(
        VoiceTransportConfig(
            transport_name="vapi",
            settings={"assistant_id": "assistant-1"},
            credentials={"api_key": "test-key"},
        ),
        websocket_factory=lambda url, timeout: socket,
    )
    session = type(
        "Session",
        (),
        {
            "metadata": {"websocket_call_url": "wss://example.test/call-1"},
        },
    )()

    transport.connect(session)

    try:
        transport.send_audio(b"\x00\x00", turn_index=0)
    except VoiceTransportError as exc:
        assert "already closed" in str(exc)
    else:
        raise AssertionError("Expected send_audio to reject a closed websocket")

    transport.hang_up(session)

    assert socket.sent == []
