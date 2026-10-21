from __future__ import annotations

import json
import io
import wave
from unittest.mock import patch

from app.calling.config import CallingProviderConfig
from app.calling.models import CallDirection, CallProvider, CallSession, CallStatus
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


def _vapi_provider():
    return VapiProvider(
        CallingProviderConfig(
            provider_name="vapi",
            credentials={"api_key": "test-key"},
            settings={"assistant_id": "assistant-1"},
        )
    )


def _in_progress_session():
    return CallSession(
        direction=CallDirection.inbound,
        provider=CallProvider.vapi,
        provider_name="vapi",
        provider_call_id="call-1",
        status=CallStatus.in_progress,
        provider_metadata={},
    )


def _completed_body():
    return {
        "id": "call-1",
        "status": "ended",
        "endedReason": "customer-ended-call",
        "startedAt": "2026-10-14T00:00:00Z",
        "endedAt": "2026-10-14T00:00:04Z",
        "transcript": "Assistant: Hello\nUser: Hi",
        "recordingUrl": "https://example.test/recording.wav",
    }


def test_vapi_wait_for_completion_waits_for_terminal_artifacts(monkeypatch):
    bodies = [
        {
            "id": "call-1",
            "status": "in-progress",
            "startedAt": "2026-10-14T00:00:00Z",
        },
        _completed_body(),
    ]
    calls = []

    def get(url, headers, timeout):
        calls.append(url)
        return Response(bodies[min(len(calls) - 1, len(bodies) - 1)])

    monkeypatch.setattr("app.calling.providers.vapi.requests.get", get)
    monkeypatch.setattr("app.calling.providers.vapi.time.sleep", lambda *_args, **_kwargs: None)

    completed = _vapi_provider().wait_for_completion(
        _in_progress_session(), timeout_seconds=5, poll_interval_seconds=0.1
    )

    assert completed.status == CallStatus.completed
    assert completed.ended_at == "2026-10-14T00:00:04Z"
    assert completed.provider_metadata["vapi_response"]["recordingUrl"] == "https://example.test/recording.wav"
    assert len(calls) == 2


def test_vapi_wait_for_completion_times_out_while_still_in_progress(monkeypatch):
    monkeypatch.setattr(
        "app.calling.providers.vapi.requests.get",
        lambda *args, **kwargs: Response({"id": "call-1", "status": "in-progress"}),
    )
    times = iter([0.0, 0.0, 0.1, 0.2, 0.3])
    monkeypatch.setattr("app.calling.providers.vapi.time.monotonic", lambda: next(times))
    monkeypatch.setattr("app.calling.providers.vapi.time.sleep", lambda *_args, **_kwargs: None)

    result = _vapi_provider().wait_for_completion(
        _in_progress_session(), timeout_seconds=0.25, poll_interval_seconds=0.1
    )

    assert result.status == CallStatus.timed_out


def test_vapi_wait_for_completion_returns_immediate_terminal_success(monkeypatch):
    calls = []

    def get(*args, **kwargs):
        calls.append(1)
        return Response(_completed_body())

    monkeypatch.setattr("app.calling.providers.vapi.requests.get", get)
    monkeypatch.setattr(
        "app.calling.providers.vapi.time.sleep",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected sleep")),
    )

    result = _vapi_provider().wait_for_completion(_in_progress_session())

    assert result.status == CallStatus.completed
    assert len(calls) == 1


def test_vapi_wait_for_completion_preserves_terminal_provider_failure(monkeypatch):
    calls = []

    def get(*args, **kwargs):
        calls.append(1)
        return Response({"id": "call-1", "status": "failed", "endedAt": "2026-10-14T00:00:04Z"})

    monkeypatch.setattr("app.calling.providers.vapi.requests.get", get)
    monkeypatch.setattr(
        "app.calling.providers.vapi.time.sleep",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected sleep")),
    )

    result = _vapi_provider().wait_for_completion(_in_progress_session())

    assert result.status == CallStatus.failed
    assert len(calls) == 1


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.timeout = None
        self.messages = [
            json.dumps({"type": "speech-update", "status": "started", "role": "assistant"}),
            b"\x00\x00",
            b"\x01\x00",
            json.dumps({"type": "speech-update", "status": "stopped", "role": "assistant"}),
        ]
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
    assert len(audio) > len(b"\x00\x00")
    assert transport.control_messages[0]["status"] == "started"
    assert transport.control_messages[1]["status"] == "stopped"
    assert len(socket.sent) == 1
    assert socket.closed is True


def test_vapi_voice_transport_returns_complete_assistant_utterance():
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
    audio = transport.receive_audio(timeout_seconds=1)

    with wave.open(io.BytesIO(audio), "rb") as wav:
        frames = wav.readframes(wav.getnframes())

    assert frames == b"\x00\x00\x01\x00"
    assert len(socket.messages) == 0


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


def test_vapi_voice_transport_endpoints_trailing_silence_preventing_60s_gap():
    # 10 speech frames of 2400 bytes at 24kHz = 0.5s of speech
    speech_frame = b"\x50\x20" * 1200  # RMS > 1000
    silence_frame = b"\x00" * 2400  # RMS = 0

    # 10 speech frames (0.5s) followed by 1200 silence frames (60s worth of silence)
    # with NO speech-update: stopped event sent.
    messages = [speech_frame] * 10 + [silence_frame] * 1200

    class LongSilenceSocket(FakeSocket):
        def __init__(self, msgs):
            super().__init__()
            self.messages = list(msgs)

    socket = LongSilenceSocket(messages)
    transport = VapiVoiceTransport(
        VoiceTransportConfig(
            transport_name="vapi",
            settings={
                "assistant_id": "assistant-1",
                "audio_format": {"sampleRate": 24000},
                "silence_endpoint_seconds": 1.2,
            },
            credentials={"api_key": "test-key"},
        ),
        websocket_factory=lambda url, timeout: socket,
    )
    session = type("Session", (), {"metadata": {"websocket_call_url": "wss://example.test/call-1"}})()
    transport.connect(session)

    audio = transport.receive_audio(timeout_seconds=30)
    with wave.open(io.BytesIO(audio), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()

    # Utterance should be promptly endpointed at ~0.5s speech + ~1.2s silence (~1.7s)
    # and MUST NOT buffer the full 60 seconds of silence frames!
    assert 1.5 <= duration <= 3.0
    assert duration < 60.0  # Does NOT exceed STT 60s limit
    # The socket should still have the vast majority of silence frames unread (~1176 unread frames)
    assert len(socket.messages) > 1100


def test_vapi_voice_transport_handles_speech_stop_before_audio_chunks():
    speech_frame = b"\x50\x20" * 1200
    silence_frame = b"\x00" * 2400
    messages = [
        json.dumps({"type": "speech-update", "status": "stopped", "role": "assistant"}),
        speech_frame,
        speech_frame,
        silence_frame,
    ]

    class EarlyStopSocket(FakeSocket):
        def __init__(self, msgs):
            super().__init__()
            self.messages = list(msgs)

    socket = EarlyStopSocket(messages)
    transport = VapiVoiceTransport(
        VoiceTransportConfig(
            transport_name="vapi",
            settings={"assistant_id": "assistant-1", "audio_format": {"sampleRate": 24000}},
            credentials={"api_key": "test-key"},
        ),
        websocket_factory=lambda url, timeout: socket,
    )
    session = type("Session", (), {"metadata": {"websocket_call_url": "wss://example.test/call-1"}})()
    transport.connect(session)

    audio = transport.receive_audio(timeout_seconds=5)
    with wave.open(io.BytesIO(audio), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
    assert duration < 2.0


def test_vapi_voice_transport_completes_on_final_transcript():
    speech_frame = b"\x50\x20" * 1200
    messages = [
        speech_frame,
        speech_frame,
        json.dumps({"type": "transcript", "role": "assistant", "transcriptType": "final", "transcript": "Hello,."}),
    ]

    class FinalTranscriptSocket(FakeSocket):
        def __init__(self, msgs):
            super().__init__()
            self.messages = list(msgs)

    socket = FinalTranscriptSocket(messages)
    transport = VapiVoiceTransport(
        VoiceTransportConfig(
            transport_name="vapi",
            settings={"assistant_id": "assistant-1", "audio_format": {"sampleRate": 24000}},
            credentials={"api_key": "test-key"},
        ),
        websocket_factory=lambda url, timeout: socket,
    )
    session = type("Session", (), {"metadata": {"websocket_call_url": "wss://example.test/call-1"}})()
    transport.connect(session)

    audio = transport.receive_audio(timeout_seconds=5)
    with wave.open(io.BytesIO(audio), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
    assert duration < 2.0


def test_vapi_voice_transport_times_out_when_only_silence_received():
    silence_frame = b"\x00" * 2400

    class InfiniteSilenceSocket(FakeSocket):
        def recv(self):
            return silence_frame

    socket = InfiniteSilenceSocket()
    transport = VapiVoiceTransport(
        VoiceTransportConfig(
            transport_name="vapi",
            settings={"assistant_id": "assistant-1", "audio_format": {"sampleRate": 24000}},
            credentials={"api_key": "test-key"},
        ),
        websocket_factory=lambda url, timeout: socket,
    )
    session = type("Session", (), {"metadata": {"websocket_call_url": "wss://example.test/call-1"}})()
    transport.connect(session)

    import pytest

    with pytest.raises(TimeoutError):
        transport.receive_audio(timeout_seconds=0.3)
