from __future__ import annotations

import io
import struct
import wave

from starlette.requests import Request

from app.calling.audio_recorder import EvaluationAudioRecorder
from app.calling.models import CallDirection, CallStatus
from app.calling.recording_artifacts import persist_recordings
from app.calling.scenario import CallingScenario
from app.calling.voice_conversation_runner import VoiceConversationRunner
from app.calling.voice_transport import VoiceTransport, VoiceTransportSession
from app.evaluations_api import download_evaluation_recording, play_evaluation_recording
from app.evaluation_store import save_evaluation_report


def _pcm(value: int, frames: int) -> bytes:
    return struct.pack("<h", value) * frames


def _read_wav(path):
    with wave.open(str(path), "rb") as wav:
        return {
            "rate": wav.getframerate(),
            "channels": wav.getnchannels(),
            "width": wav.getsampwidth(),
            "frames": wav.getnframes(),
            "pcm": wav.readframes(wav.getnframes()),
        }


def _recorder(monkeypatch, tmp_path, session_id="session-1"):
    import app.calling.audio_recorder as recorder_module

    monkeypatch.setattr(recorder_module, "_CAPTURE_ROOT", tmp_path / "capture")
    return EvaluationAudioRecorder(session_id=session_id, sample_rate=1000, clock=lambda: 0.0)


def test_agent_only_audio_is_captured_with_session_silence(monkeypatch, tmp_path):
    recorder = _recorder(monkeypatch, tmp_path)
    recorder.on_remote_audio(_pcm(1000, 1000), sample_rate=1000, timestamp=1.0)

    artifact = recorder.finalize()
    audio = _read_wav(artifact.path)

    assert artifact.metadata["source"] == "evalforge"
    assert artifact.duration_seconds == 2.0
    assert audio["frames"] == 2000
    assert audio["pcm"][:2000] == b"\x00" * 2000
    assert len(audio["pcm"]) > 0


def test_persona_only_audio_is_captured(monkeypatch, tmp_path):
    recorder = _recorder(monkeypatch, tmp_path)
    recorder.on_local_audio(_pcm(800, 500), sample_rate=1000, timestamp=0.0)

    artifact = recorder.finalize()
    audio = _read_wav(artifact.path)

    assert artifact.duration_seconds == 0.5
    assert audio["pcm"] == _pcm(800, 500)


def test_alternating_audio_preserves_gap_and_duration(monkeypatch, tmp_path):
    recorder = _recorder(monkeypatch, tmp_path)
    recorder.on_remote_audio(_pcm(500, 1000), sample_rate=1000, timestamp=0.0)
    recorder.on_local_audio(_pcm(700, 1000), sample_rate=1000, timestamp=2.0)

    artifact = recorder.finalize()
    audio = _read_wav(artifact.path)

    assert artifact.duration_seconds == 3.0
    assert audio["pcm"][2000:4000] == b"\x00" * 2000


def test_overlapping_tracks_are_mixed_not_serialized(monkeypatch, tmp_path):
    recorder = _recorder(monkeypatch, tmp_path)
    recorder.on_remote_audio(_pcm(1000, 1000), sample_rate=1000, timestamp=0.0)
    recorder.on_local_audio(_pcm(1000, 1000), sample_rate=1000, timestamp=0.5)

    artifact = recorder.finalize()
    audio = _read_wav(artifact.path)
    samples = struct.unpack(f"<{audio['frames']}h", audio["pcm"])

    assert artifact.duration_seconds == 1.5
    assert samples[250] == 1000
    assert samples[750] == 2000
    assert samples[1250] == 1000


def test_recording_persists_and_playback_and_download_serve_it(monkeypatch, tmp_path):
    import app.calling.recording_artifacts as artifacts
    from app.config import settings

    recorder = _recorder(monkeypatch, tmp_path)
    recorder.on_remote_audio(_pcm(1000, 1000), sample_rate=1000, timestamp=0.0)
    captured = recorder.finalize().model_dump(mode="json")
    monkeypatch.setattr(artifacts, "_ROOT", tmp_path / "artifacts")
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "evaluations.db"))

    prepared, status, audio = persist_recordings([captured], "eval-captured")
    save_evaluation_report({
        "evaluation_id": "eval-captured",
        "connection_id": "calling-1",
        "scenario_id": "scenario-1",
        "created_at": "2026-10-23T00:00:00+00:00",
        "recording_metadata": prepared,
        "conversation_audio": audio,
    })
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    playback = play_evaluation_recording("eval-captured", "full_call", request)
    download = download_evaluation_recording("eval-captured", "full_call", request)

    assert status == "available"
    assert prepared[0]["path"].replace("\\", "/") == "eval-captured/full_call.wav"
    assert audio["full"].endswith("/full_call/playback")
    assert playback.status_code == 200
    assert download.status_code == 200


class _TextTransport(VoiceTransport):
    def connect(self, session):
        pass

    def receive_text(self, timeout_seconds=30):
        return "Hello"

    def send_text(self, text, turn_index=0):
        pass

    def hang_up(self, session):
        pass


class _BrokenRecorder:
    def __init__(self, **kwargs):
        pass

    def finalize(self):
        raise RuntimeError("recording failed")


def test_recording_failure_does_not_fail_conversation():
    scenario = CallingScenario(
        scenario_id="recording-failure",
        agent={"channel": "calling", "adapter": "test"},
        persona={"name": "Caller", "goal": "Ask for help", "tone": "neutral"},
    )
    runner = VoiceConversationRunner(
        simulator=lambda persona, transcript: {"message": "Thanks."},
        max_turns=1,
        audio_recorder_factory=_BrokenRecorder,
    )

    transcript = runner.run(
        persona=scenario.persona,
        transport=_TextTransport(),
        session=VoiceTransportSession(
            transport_name="test",
            transport_call_id="call-1",
            direction=CallDirection.inbound,
            status=CallStatus.in_progress,
        ),
        session_id="session-1",
        run_id="run-1",
    )

    assert [turn.text for turn in transcript.turns] == ["Hello", "Thanks."]
    assert runner.recordings == []


def test_provider_recording_remains_fallback_when_internal_capture_is_missing(monkeypatch, tmp_path):
    import app.calling.recording_artifacts as artifacts
    from tests.test_calling_failure_analysis_and_recordings import _RecordingResponse, _wav_bytes

    monkeypatch.setattr(artifacts, "_ROOT", tmp_path / "artifacts")
    monkeypatch.setattr(artifacts.requests, "get", lambda *args, **kwargs: _RecordingResponse(_wav_bytes()))

    prepared, status, audio = persist_recordings(
        [{
            "artifact_id": "provider-full",
            "remote_url": "https://provider.test/full.wav",
            "format": "wav",
            "provider_name": "provider",
            "metadata": {"source": "provider"},
        }],
        "eval-provider-fallback",
    )

    assert status == "available"
    assert prepared[0]["status"] == "available"
    assert audio["full"].endswith("/provider-full/playback")


def test_valid_internal_capture_prevents_provider_fallback_download(monkeypatch, tmp_path):
    import app.calling.recording_artifacts as artifacts

    recorder = _recorder(monkeypatch, tmp_path)
    recorder.on_remote_audio(_pcm(1000, 1000), sample_rate=1000, timestamp=0.0)
    captured = recorder.finalize().model_dump(mode="json")
    monkeypatch.setattr(artifacts, "_ROOT", tmp_path / "artifacts")
    monkeypatch.setattr(
        artifacts.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider download not expected")),
    )

    prepared, status, audio = persist_recordings(
        [
            captured,
            {
                "artifact_id": "provider-full",
                "remote_url": "https://provider.test/full.wav",
                "format": "wav",
                "provider_name": "provider",
                "metadata": {"source": "provider"},
            },
        ],
        "eval-internal-primary",
    )

    assert status == "available"
    assert prepared[0]["status"] == "available"
    assert prepared[1]["status"] == "fallback_not_needed"
    assert "remote_url" not in prepared[1]
    assert audio["full"].endswith("/full_call/playback")
