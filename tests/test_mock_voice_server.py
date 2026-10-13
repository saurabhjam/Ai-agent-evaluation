import io
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Mock STT/TTS dependencies before importing the app
with patch("app.adapters.voice.local.FasterWhisperSTT") as mock_stt_class, \
     patch("app.adapters.voice.local.PiperTTS") as mock_tts_class:
    
    # Configure the mocked instances
    mock_stt_instance = mock_stt_class.return_value
    mock_stt_instance.transcribe.return_value = "fake transcript"
    
    mock_tts_instance = mock_tts_class.return_value
    mock_tts_instance.synthesize.return_value = b"fake_wav_bytes"
    
    from mock_voice_server import app, stt_provider, tts_provider

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "mock-voice-agent"}

def test_process_voice_missing_file():
    # Sending without multipart file
    response = client.post("/api/voice")
    assert response.status_code == 422 # Unprocessable Entity (FastAPI default for missing required file)

def test_process_voice_empty_file():
    files = {"audio": ("test.wav", b"", "audio/wav")}
    response = client.post("/api/voice", files=files)
    assert response.status_code == 400
    assert response.json() == {"detail": "Empty audio file."}

def test_process_voice_valid_refund(monkeypatch):
    # Setup mock to return "refund"
    stt_provider.transcribe.return_value = "I want a refund"
    tts_provider.synthesize.return_value = b"RIFFfake_wav"
    
    files = {"audio": ("test.wav", b"fake_user_audio", "audio/wav")}
    response = client.post("/api/voice", files=files)
    
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == b"RIFFfake_wav"
    
    # Assert STT was called with the uploaded bytes
    stt_provider.transcribe.assert_called_with(b"fake_user_audio")
    # Assert TTS was called with the refund intent string
    tts_provider.synthesize.assert_called_with(
        "I can help you with your refund request. Please provide the order details and describe the issue with the product."
    )

def test_process_voice_valid_damage():
    stt_provider.transcribe.return_value = "It is damaged"
    tts_provider.synthesize.return_value = b"RIFFfake_wav"
    
    files = {"audio": ("test.wav", b"fake_user_audio", "audio/wav")}
    response = client.post("/api/voice", files=files)
    
    assert response.status_code == 200
    tts_provider.synthesize.assert_called_with(
        "Thank you for explaining the damage. I have recorded the issue and can continue with the refund request."
    )

def test_process_voice_valid_exit():
    stt_provider.transcribe.return_value = "goodbye"
    tts_provider.synthesize.return_value = b"RIFFfake_wav"
    
    files = {"audio": ("test.wav", b"fake_user_audio", "audio/wav")}
    response = client.post("/api/voice", files=files)
    
    assert response.status_code == 200
    tts_provider.synthesize.assert_called_with(
        "Thank you for contacting us. Goodbye."
    )

def test_process_voice_valid_unknown():
    stt_provider.transcribe.return_value = "hello"
    tts_provider.synthesize.return_value = b"RIFFfake_wav"
    
    files = {"audio": ("test.wav", b"fake_user_audio", "audio/wav")}
    response = client.post("/api/voice", files=files)
    
    assert response.status_code == 200
    tts_provider.synthesize.assert_called_with(
        "I understand. Please tell me more about what you need help with."
    )

def test_process_voice_stt_failure():
    stt_provider.transcribe.side_effect = Exception("STT Error")
    
    files = {"audio": ("test.wav", b"fake_user_audio", "audio/wav")}
    response = client.post("/api/voice", files=files)
    
    assert response.status_code == 500
    assert "Transcription failed" in response.json()["detail"]
    stt_provider.transcribe.side_effect = None # reset

def test_process_voice_tts_failure():
    stt_provider.transcribe.return_value = "hello"
    tts_provider.synthesize.side_effect = Exception("TTS Error")
    
    files = {"audio": ("test.wav", b"fake_user_audio", "audio/wav")}
    response = client.post("/api/voice", files=files)
    
    assert response.status_code == 500
    assert "Synthesis failed" in response.json()["detail"]
    tts_provider.synthesize.side_effect = None # reset
