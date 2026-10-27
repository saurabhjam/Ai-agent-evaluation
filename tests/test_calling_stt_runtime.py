import io
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch
import wave

from app.adapters.voice.local import FasterWhisperSTT, _inspect_audio_bytes
from app.calling.voice_transport import VapiVoiceTransport, VoiceTransportConfig


def wav(pcm, rate=24000):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as out:
        out.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        out.writeframes(pcm)
    return stream.getvalue()


def test_pcm_duration_and_silence_use_header_sample_rate():
    info = _inspect_audio_bytes(wav(b"\0\0" * 24000), fallback_sample_rate=16000)
    assert info["duration_seconds"] == 1
    assert info["pcm_samples"] == 24000
    assert info["pcm_bytes"] == 48000
    assert info["sample_rate"] == 24000
    assert info["rms_below_60_seconds"] == 1


def test_stt_times_lazy_materialization_and_releases_input(monkeypatch):
    import faster_whisper.audio
    from app.adapters.voice import local
    clock = [0.0]
    monkeypatch.setattr(local.time, "perf_counter", lambda: clock[0])
    model = Mock()
    def acquire():
        clock[0] += 1
        return model
    def decode(stream):
        clock[0] += 3
        return "decoded waveform"
    def transcribe(audio, **kwargs):
        assert audio == "decoded waveform"
        assert kwargs == {"language": "en", "beam_size": 1}
        clock[0] += 2
        def segments():
            clock[0] += 5
            yield SimpleNamespace(text=" Same answer ")
        return segments(), None
    monkeypatch.setattr(faster_whisper.audio, "decode_audio", decode)
    stt = FasterWhisperSTT(language="en")
    monkeypatch.setattr(stt, "_get_model", acquire)
    model.transcribe.side_effect = transcribe
    assert stt.transcribe(wav(b"\1\0" * 2400)) == "Same answer"
    timing = stt.last_transcription_timing
    assert timing["model_acquisition_ms"] == 1000
    assert timing["preprocessing_ms"] == 3000
    assert timing["invocation_ms"] == 2000
    assert timing["segment_materialization_ms"] == 5000
    assert timing["total_ms"] == 11000
    assert not any(isinstance(v, bytes) for v in timing.values())


def test_whisper_concurrent_acquisition_constructs_one_model(monkeypatch):
    import faster_whisper
    from app.adapters.voice import local
    model = object()
    constructor = Mock(return_value=model)
    monkeypatch.setattr(faster_whisper, "WhisperModel", constructor)
    key = ("offline-concurrency-test", "cpu", "int8", 4)
    local._WHISPER_MODEL_CACHE.pop(key, None)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: FasterWhisperSTT(model_size=key[0], cpu_threads=4)._get_model(), range(16)))
    assert all(item is model for item in results)
    constructor.assert_called_once()
    local._WHISPER_MODEL_CACHE.pop(key)


def test_utterance_buffers_reset_and_duplicate_stop_cannot_replay_audio():
    start = json.dumps({"type": "speech-update", "role": "assistant", "status": "started"})
    stop = json.dumps({"type": "speech-update", "role": "assistant", "status": "stopped"})
    first, second = b"\1\0" * 480, b"\2\0" * 480
    messages = iter([start, first, stop, stop, start, second, stop])
    transport = VapiVoiceTransport(VoiceTransportConfig(transport_name="vapi"), provider=Mock())
    transport.websocket = SimpleNamespace(connected=True, recv=lambda: next(messages), settimeout=lambda _: None)
    for expected in (first, second):
        result = transport.receive_audio()
        with wave.open(io.BytesIO(result), "rb") as audio:
            assert audio.getframerate() == 24000
            assert audio.readframes(audio.getnframes()) == expected
        assert transport.last_utterance_complete()


def test_long_leading_silence_does_not_expand_turn_buffer():
    stop = json.dumps({"type": "speech-update", "role": "assistant", "status": "stopped"})
    messages = iter([b"\0\0" * 480] * 1000 + [b"\xff\x7f" * 480, stop])
    transport = VapiVoiceTransport(VoiceTransportConfig(transport_name="vapi"), provider=Mock())
    transport.websocket = SimpleNamespace(connected=True, recv=lambda: next(messages), settimeout=lambda _: None)
    result = transport.receive_audio()
    assert _inspect_audio_bytes(result)["duration_seconds"] <= 0.52


def test_scenario_language_hint_is_optional_and_connection_can_override():
    from app.calling.execution_context import CallingExecutionContext
    from app.calling.execution_pipeline import _voice_conversation_runner
    from app.calling.config import CallingProviderConfig
    from app.calling.scenario import CallingScenario

    scenario = CallingScenario(scenario_id="stt-language", agent={"channel": "calling", "adapter": "mock", "config": {"stt": {"language": "en"}}}, persona={"name": "Alex", "goal": "Ask for help", "tone": "polite"})
    context = CallingExecutionContext(scenario=scenario, provider_config=CallingProviderConfig(provider_name="mock"))
    assert _voice_conversation_runner(context).stt_provider.language == "en"
    context.provider_config.settings["stt"] = {"language": "fr"}
    assert _voice_conversation_runner(context).stt_provider.language == "fr"
    context.provider_config.settings.clear()
    scenario.agent.config.clear()
    assert _voice_conversation_runner(context).stt_provider.language is None
