import wave
import struct
import math
from pathlib import Path
from app.voice.audio import trim_leading_silence, resample_pcm

def create_test_wav(path: Path, pcm_data: bytes, framerate: int = 16000):
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(pcm_data)

def test_trim_leading_silence_with_speech(tmp_path):
    raw_path = tmp_path / "raw.wav"
    clean_path = tmp_path / "clean.wav"
    
    # Generate 1 sec of pure silence (0s), then 1 sec of loud noise (30000)
    silence = struct.pack("<16000h", *([0] * 16000))
    speech = struct.pack("<16000h", *([30000] * 16000))
    create_test_wav(raw_path, silence + speech)
    
    raw_ms, silence_ms, clean_ms = trim_leading_silence(raw_path, clean_path, threshold_rms=50, chunk_ms=10, min_speech_ms=100)
    
    assert raw_ms == 2000
    assert silence_ms == 1000
    assert clean_ms == 1000
    assert clean_path.exists()
    
    # Verify clean file has exactly 1 sec
    with wave.open(str(clean_path), 'rb') as wf:
        assert wf.getnframes() == 16000

def test_trim_leading_silence_no_silence(tmp_path):
    raw_path = tmp_path / "raw.wav"
    clean_path = tmp_path / "clean.wav"
    
    # Generate 1 sec of loud noise only
    speech = struct.pack("<16000h", *([30000] * 16000))
    create_test_wav(raw_path, speech)
    
    raw_ms, silence_ms, clean_ms = trim_leading_silence(raw_path, clean_path, threshold_rms=50, chunk_ms=10, min_speech_ms=100)
    
    assert raw_ms == 1000
    assert silence_ms == 0
    assert clean_ms == 1000
    
    with wave.open(str(clean_path), 'rb') as wf:
        assert wf.getnframes() == 16000

def test_trim_leading_silence_all_silence(tmp_path):
    raw_path = tmp_path / "raw.wav"
    clean_path = tmp_path / "clean.wav"
    
    # Generate 1 sec of pure silence only
    silence = struct.pack("<16000h", *([0] * 16000))
    create_test_wav(raw_path, silence)
    
    raw_ms, silence_ms, clean_ms = trim_leading_silence(raw_path, clean_path, threshold_rms=50, chunk_ms=10, min_speech_ms=100)
    
    assert raw_ms == 1000
    assert silence_ms == 1000  # defaults to trimming everything if no speech found
    assert clean_ms == 0
    
    with wave.open(str(clean_path), 'rb') as wf:
        assert wf.getnframes() == 0

def test_trim_leading_silence_low_volume_ignored(tmp_path):
    raw_path = tmp_path / "raw.wav"
    clean_path = tmp_path / "clean.wav"
    
    # Generate 1 sec of volume below threshold (e.g. amplitude 10 -> RMS ~10), then loud speech
    low_vol = struct.pack("<16000h", *([10] * 16000))
    speech = struct.pack("<16000h", *([30000] * 16000))
    create_test_wav(raw_path, low_vol + speech)
    
    raw_ms, silence_ms, clean_ms = trim_leading_silence(raw_path, clean_path, threshold_rms=50, chunk_ms=10, min_speech_ms=100)
    
    # Low volume should be treated as silence because it's below the 50 RMS threshold
    assert silence_ms == 1000

def test_trim_leading_silence_click_ignored(tmp_path):
    raw_path = tmp_path / "raw.wav"
    clean_path = tmp_path / "clean.wav"
    
    # Silence (500ms), followed by loud click (50ms), silence (450ms), speech (1000ms)
    s1 = struct.pack("<8000h", *([0] * 8000))       # 500ms silence
    click = struct.pack("<800h", *([30000] * 800))  # 50ms click
    s2 = struct.pack("<7200h", *([0] * 7200))       # 450ms silence
    speech = struct.pack("<16000h", *([30000] * 16000)) # 1000ms speech
    
    create_test_wav(raw_path, s1 + click + s2 + speech)
    
    # min_speech_ms is 100, so the 50ms click should be ignored
    raw_ms, silence_ms, clean_ms = trim_leading_silence(raw_path, clean_path, threshold_rms=50, chunk_ms=10, min_speech_ms=100)
    
    assert raw_ms == 2000
    assert silence_ms == 1000 # skips the click entirely!

def test_resample_pcm_same_rate():
    # 16kHz to 16kHz should return same bytes
    pcm_data = b"1234"
    assert resample_pcm(pcm_data, 16000, 16000) == pcm_data

def test_resample_pcm_downsample():
    # Generate exactly 1 second of 48kHz audio (96000 bytes)
    pcm_data = struct.pack("<48000h", *([1000] * 48000))
    # Downsample to 16kHz
    resampled = resample_pcm(pcm_data, 48000, 16000)
    # The resulting audio should be exactly 1 second at 16kHz (32000 bytes)
    assert len(resampled) == 32000
