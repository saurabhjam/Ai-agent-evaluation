"""
Tests for the automated VoicePersonaEngine and related CLI loop.
"""

import os
import json
import wave
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from app.schemas import Persona
from app.voice.persona import VoicePersonaEngine
from app.models.voice import VoiceConversation, VoiceSession, SessionStatus, VoiceTurn, Speaker


@pytest.fixture
def mock_persona():
    return Persona(
        name="Test Persona",
        goal="Test goal to achieve",
        tone="neutral"
    )

@pytest.fixture
def mock_adapter():
    adapter = MagicMock()
    adapter.start_session.return_value = "test-session-123"
    
    # Setup mock conversation for end_session
    mock_vc = MagicMock(spec=VoiceConversation)
    mock_vc.session = VoiceSession(session_id="test-session-123", channel="voice", started_at="", status=SessionStatus.completed)
    mock_vc.turns = []
    adapter.end_session.return_value = mock_vc
    
    adapter.get_transcript.return_value = []
    
    return adapter

@pytest.fixture
def mock_tts():
    tts = MagicMock()
    tts.synthesize.return_value = b"fake-wav-bytes"
    return tts

@patch("app.voice.persona.generate_next_user_turn")
def test_voice_persona_engine_basic_loop(mock_generate, mock_persona, mock_adapter, mock_tts):
    """Test the persona engine loops, calls TTS, and interacts with the adapter."""
    
    # Persona says something, then says END_CONVERSATION
    mock_generate.side_effect = [
        {"message": "Hello agent", "attachments": None},
        {"message": "[END_CONVERSATION]", "attachments": None}
    ]
    
    engine = VoicePersonaEngine(
        persona=mock_persona,
        adapter=mock_adapter,
        tts_provider=mock_tts,
        max_turns=5
    )
    
    vc = engine.run_automated_session()
    
    # It should have called generate twice
    assert mock_generate.call_count == 2
    
    # It should have called TTS once (for "Hello agent")
    mock_tts.synthesize.assert_called_once_with("Hello agent")
    
    # It should have sent audio and received audio once
    mock_adapter.send_audio.assert_called_once_with(b"fake-wav-bytes", turn_index=0)
    mock_adapter.receive_audio.assert_called_once()
    

@patch("app.voice.persona.generate_next_user_turn")
def test_voice_persona_engine_max_turns(mock_generate, mock_persona, mock_adapter, mock_tts):
    """Ensure it stops when max_turns is reached without END_CONVERSATION."""
    mock_generate.return_value = {"message": "Still talking"}
    
    engine = VoicePersonaEngine(
        persona=mock_persona,
        adapter=mock_adapter,
        tts_provider=mock_tts,
        max_turns=3
    )
    
    engine.run_automated_session()
    
    assert mock_generate.call_count == 3
    assert mock_tts.synthesize.call_count == 3
    assert mock_adapter.send_audio.call_count == 3

@patch("app.voice.persona.time.time")
@patch("app.voice.persona.generate_next_user_turn")
def test_voice_persona_engine_max_duration(mock_generate, mock_time, mock_persona, mock_adapter, mock_tts):
    """Ensure it stops when max_session_duration_seconds is exceeded."""
    mock_generate.return_value = {"message": "Talking"}
    
    import itertools
    time_vals = itertools.count(start=0, step=100)
    mock_time.side_effect = lambda: next(time_vals)
    
    engine = VoicePersonaEngine(
        persona=mock_persona,
        adapter=mock_adapter,
        tts_provider=mock_tts,
        max_turns=10,
        max_session_duration_seconds=300
    )
    
    engine.run_automated_session()
    
    # Should only complete one turn
    assert mock_generate.call_count == 1
    assert mock_tts.synthesize.call_count == 1


def test_generate_full_audio_and_json(tmp_path):
    """Test that the full WAV is created properly and JSON is generated."""
    # Create fake individual WAV files
    user_wav = tmp_path / "user.wav"
    agent_wav = tmp_path / "agent.wav"
    
    for wav_file in (user_wav, agent_wav):
        with wave.open(str(wav_file), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            if wav_file == agent_wav:
                wf.setframerate(48000)
                # Give agent 1 sec of speech at 48kHz (48000 frames)
                wf.writeframes(b"\x7f\x7f" * 48000)
            else:
                wf.setframerate(16000)
                # Give user 1 sec silence at 16kHz
                wf.writeframes(b"\x00\x00" * 16000)
            
    mock_vc = VoiceConversation(
        session=VoiceSession(session_id="sess-123", channel="voice", started_at="", status=SessionStatus.completed),
        turns=[
            VoiceTurn(speaker=Speaker.user, text="User text", audio_path=str(user_wav)),
            VoiceTurn(speaker=Speaker.agent, text="Agent text", audio_path=str(agent_wav))
        ],
        events=[], tool_calls=[], tool_results=[], handoff_events=[]
    )
    
    conv_data = VoicePersonaEngine.generate_full_audio_and_json(mock_vc, tmp_path, "test_scenario")
    
    assert "sess-123" == conv_data["session_id"]
    assert len(conv_data["turns"]) == 2
    assert conv_data["turns"][0]["speaker"] == "user"
    assert conv_data["turns"][1]["speaker"] == "agent"
    
    full_wav = tmp_path / "full_conversation.wav"
    assert full_wav.exists()
    assert str(full_wav.absolute()) == conv_data["full_audio_path"]
    
    # Verify WAV header
    with wave.open(str(full_wav), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 16000
        # 2 files * 1 sec (16000 frames) + 1 gap * 0.3 sec (4800 frames) = 36800 frames
        assert wf.getnframes() == 36800

    json_path = tmp_path / "conversation.json"
    assert json_path.exists()
    with open(json_path) as f:
        data = json.load(f)
        assert data["session_id"] == "sess-123"
        assert len(data["turns"]) == 2
