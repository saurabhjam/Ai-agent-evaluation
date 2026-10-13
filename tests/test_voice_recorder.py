"""
Tests for the local microphone recorder.
"""

import sys
import io
import wave
import pytest
from unittest.mock import MagicMock, patch

from app.voice.recorder import VoiceRecorder


@pytest.fixture
def mock_sounddevice():
    # Actually it's easier to patch sys.modules to mock sounddevice and numpy
    mock_sd = MagicMock()
    mock_np = MagicMock()
        
    # Setup mock return for recording
    # Generate 1 second of fake 16-bit PCM silence (16000 samples)
    fake_pcm = b"\x00\x00" * 16000
    # Numpy returns something with a tobytes() method
    mock_recording = MagicMock()
    mock_recording.tobytes.return_value = fake_pcm
    mock_sd.rec.return_value = mock_recording
    
    # Numpy frombuffer and VAD helpers
    mock_np.frombuffer.return_value = []
    mock_np.int16 = "int16"
    mock_np.float32 = "float32"
    mock_np.sqrt = lambda x: x
    mock_np.mean = lambda x: x
    mock_np.concatenate.return_value = mock_recording

        
    sys.modules["sounddevice"] = mock_sd
    sys.modules["numpy"] = mock_np
    
    yield mock_sd, mock_np
    
    del sys.modules["sounddevice"]
    del sys.modules["numpy"]


def test_recorder_lazy_loading(mock_sounddevice):
    """Ensure it doesn't crash on import/init without deps."""
    recorder = VoiceRecorder()
    assert recorder._sd is None
    assert recorder._np is None


def test_recorder_record_audio(mock_sounddevice):
    mock_sd, _ = mock_sounddevice
    recorder = VoiceRecorder(sample_rate=16000)
    
    wav_bytes = recorder.record_audio(duration_seconds=1.0, use_vad=False)
    
    # Assert sounddevice rec was called
    mock_sd.rec.assert_called_once_with(16000, samplerate=16000, channels=1, dtype='int16')
    mock_sd.wait.assert_called_once()
    
    # Assert WAV container was generated
    assert wav_bytes.startswith(b"RIFF")
    
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000


def test_recorder_play_audio(mock_sounddevice):
    mock_sd, mock_np = mock_sounddevice
    recorder = VoiceRecorder(sample_rate=16000)
    
    # Create fake valid WAV bytes
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 10)
    
    wav_bytes = buf.getvalue()
    
    recorder.play_audio(wav_bytes)
    
    mock_np.frombuffer.assert_called_once()
    mock_sd.play.assert_called_once()
    mock_sd.wait.assert_called_once()


def test_recorder_missing_deps():
    # Force import error for sounddevice
    with patch.dict(sys.modules, {"sounddevice": None}):
        recorder = VoiceRecorder()
        with pytest.raises(ImportError, match="requires 'sounddevice'"):
            recorder._ensure_deps()


def test_recorder_vad_speech_then_silence(mock_sounddevice):
    mock_sd, mock_np = mock_sounddevice
    recorder = VoiceRecorder(sample_rate=16000, vad_threshold=100.0)

    # Mock InputStream
    mock_stream_ctx = MagicMock()
    mock_stream = MagicMock()
    mock_stream_ctx.__enter__.return_value = mock_stream
    mock_sd.InputStream.return_value = mock_stream_ctx

    # Simulate chunks: 4 chunks of speech (0.4s), then 10 chunks of silence (1.0s)
    speech_chunk = MagicMock()
    speech_chunk.astype.return_value = speech_chunk
    
    silence_chunk = MagicMock()
    silence_chunk.astype.return_value = silence_chunk

    # Set up our mocked np functions just for this test
    def mock_sqrt(val): return val
    
    mean_calls = 0
    def mock_mean(val):
        nonlocal mean_calls
        mean_calls += 1
        if mean_calls <= 4:
            return 200.0
        return 10.0

    mock_np.sqrt = mock_sqrt
    mock_np.mean = mock_mean
    
    # Create fake PCM to be returned by concatenate
    fake_pcm = b"\x00\x00" * 16000
    mock_concat_result = MagicMock()
    mock_concat_result.tobytes.return_value = fake_pcm
    mock_np.concatenate.return_value = mock_concat_result

    # Infinite generator to avoid StopIteration
    def read_generator():
        for _ in range(4): yield (speech_chunk, False)
        while True: yield (silence_chunk, False)
        
    mock_stream.read.side_effect = read_generator()

    wav_bytes = recorder.record_audio(use_vad=True)

    assert mock_stream.read.call_count in (14, 15)
    assert wav_bytes.startswith(b"RIFF")


def test_recorder_vad_max_duration(mock_sounddevice):
    mock_sd, mock_np = mock_sounddevice
    recorder = VoiceRecorder(sample_rate=16000, max_recording_duration=1.0)

    # Mock InputStream
    mock_stream_ctx = MagicMock()
    mock_stream = MagicMock()
    mock_stream_ctx.__enter__.return_value = mock_stream
    mock_sd.InputStream.return_value = mock_stream_ctx

    speech_chunk = MagicMock()
    speech_chunk.astype.return_value = speech_chunk

    def mock_mean(val): return 200.0 # always speech
    mock_np.mean = mock_mean
    mock_np.sqrt = lambda x: x
    
    fake_pcm = b"\x00\x00" * 16000
    mock_concat_result = MagicMock()
    mock_concat_result.tobytes.return_value = fake_pcm
    mock_np.concatenate.return_value = mock_concat_result

    # Should exit after max_recording_duration (1.0s = 10 chunks)
    mock_stream.read.return_value = (speech_chunk, False)

    wav_bytes = recorder.record_audio(use_vad=True)

    # 1.0s / 0.1s chunk = 10, but float math might make it 11
    assert mock_stream.read.call_count in (10, 11)
    assert wav_bytes.startswith(b"RIFF")
