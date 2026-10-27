import sys
from types import ModuleType

from app.adapters.voice import local


def test_whisper_and_piper_models_load_once_across_provider_instances(monkeypatch, tmp_path):
    loads = {"whisper": 0, "piper": 0}

    whisper_module = ModuleType("faster_whisper")

    class WhisperModel:
        def __init__(self, *args, **kwargs):
            loads["whisper"] += 1

    whisper_module.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", whisper_module)

    piper_package = ModuleType("piper")
    piper_package.__path__ = []
    piper_voice = ModuleType("piper.voice")

    class PiperVoice:
        @staticmethod
        def load(path):
            loads["piper"] += 1
            return object()

    piper_voice.PiperVoice = PiperVoice
    monkeypatch.setitem(sys.modules, "piper", piper_package)
    monkeypatch.setitem(sys.modules, "piper.voice", piper_voice)

    model_path = tmp_path / "voice.onnx"
    model_path.write_bytes(b"model")
    local._WHISPER_MODEL_CACHE.clear()
    local._PIPER_MODEL_CACHE.clear()

    assert local.FasterWhisperSTT(model_size="cache-test")._get_model() is local.FasterWhisperSTT(model_size="cache-test")._get_model()
    assert local.PiperTTS(model_path=str(model_path))._get_model() is local.PiperTTS(model_path=str(model_path))._get_model()
    assert loads == {"whisper": 1, "piper": 1}
