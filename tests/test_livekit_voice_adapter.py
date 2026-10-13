import pytest
import os
import uuid
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path

from app.adapters.voice.livekit import LiveKitVoiceAdapter
from app.models.voice import Speaker, VoiceSession, SessionStatus

@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://fake.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "fake_key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "fake_secret")

@pytest.fixture
def adapter_config():
    return {
        "agent_name": "my-agent",
        "audio_dir": "artifacts/voice",
        "timeout": 1.0,
        "stt": {"provider": "faster_whisper", "model": "tiny", "device": "cpu", "compute_type": "int8"},
        "tts": {"provider": "piper"}
    }

@patch("app.adapters.voice.livekit.FasterWhisperSTT")
@patch("app.adapters.voice.livekit.PiperTTS")
@patch("livekit.rtc.Room")
def test_livekit_adapter_reads_from_env_file(mock_room, mock_tts, mock_stt, adapter_config, monkeypatch, tmp_path):
    # Remove vars from environ
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    
    # Create a mock .env file
    env_file = tmp_path / ".env"
    env_file.write_text("LIVEKIT_URL=wss://file.livekit\nLIVEKIT_API_KEY=file_key\nLIVEKIT_API_SECRET=file_secret\n")
    
    # Simulate run_voice_livekit's dotenv loading
    from dotenv import load_dotenv
    load_dotenv(env_file)
    
    adapter = LiveKitVoiceAdapter(config=adapter_config)
    assert adapter._url == "wss://file.livekit"
    assert adapter._api_key == "file_key"
    assert adapter._api_secret == "file_secret"

@patch("app.adapters.voice.livekit.FasterWhisperSTT")
@patch("app.adapters.voice.livekit.PiperTTS")
@patch("livekit.rtc.Room")
@patch("livekit.api.AccessToken")
def test_livekit_adapter_init(mock_access_token, mock_room, mock_tts, mock_stt, mock_env, adapter_config):
    adapter = LiveKitVoiceAdapter(config=adapter_config)
    assert adapter._url == "wss://fake.livekit.cloud"
    assert adapter._api_key == "fake_key"
    assert adapter._api_secret == "fake_secret"
    assert adapter._agent_name == "my-agent"

@patch("app.adapters.voice.livekit.FasterWhisperSTT")
@patch("app.adapters.voice.livekit.PiperTTS")
@patch("livekit.rtc.Room")
@patch("livekit.api.AccessToken")
@patch("livekit.api.LiveKitAPI")
def test_livekit_adapter_start_session(mock_livekit_api, mock_access_token, mock_room, mock_tts, mock_stt, mock_env, adapter_config):
    # Mocking AccessToken
    mock_token_instance = MagicMock()
    mock_token_instance.with_identity.return_value = mock_token_instance
    mock_token_instance.with_name.return_value = mock_token_instance
    mock_token_instance.with_grants.return_value = mock_token_instance
    mock_token_instance.to_jwt.return_value = "fake_jwt"
    mock_access_token.return_value = mock_token_instance
    
    # Mocking Room
    mock_room_instance = MagicMock()
    mock_room_instance.connect = AsyncMock()
    mock_room_instance.local_participant = MagicMock()
    mock_room_instance.local_participant.publish_track = AsyncMock()
    mock_room_instance.remote_participants = {}
    mock_room.return_value = mock_room_instance

    adapter = LiveKitVoiceAdapter(config=adapter_config)
    adapter._room = mock_room_instance
    
    # We simulate agent joining immediately to avoid timeout
    def simulate_agent_join(*args, **kwargs):
        adapter._agent_joined_event.set()
        adapter._agent_track_subscribed_event.set()
        return None
    mock_room_instance.connect.side_effect = simulate_agent_join
    
    # Mocking LiveKitAPI
    mock_api_instance = AsyncMock()
    mock_api_instance.agent_dispatch.create_dispatch = AsyncMock()
    # LiveKitAPI is used as an async context manager
    mock_api_instance.__aenter__.return_value = mock_api_instance
    mock_api_instance.__aexit__.return_value = None
    mock_livekit_api.return_value = mock_api_instance

    with patch("livekit.rtc.LocalAudioTrack.create_audio_track"):
        session_id = adapter.start_session()
        
    assert session_id is not None
    assert adapter._session is not None
    assert adapter._session.session_id == session_id
    
    # Verify LiveKitAPI dispatch was called correctly
    mock_livekit_api.assert_called_once_with(
        "wss://fake.livekit.cloud", 
        "fake_key", 
        "fake_secret"
    )
    mock_api_instance.agent_dispatch.create_dispatch.assert_called_once()
    dispatch_req = mock_api_instance.agent_dispatch.create_dispatch.call_args[0][0]
    assert dispatch_req.agent_name == "my-agent"
    assert dispatch_req.room == f"room-{session_id}"
    
    mock_room_instance.connect.assert_called_once()
    mock_room_instance.local_participant.publish_track.assert_called_once()

@patch("app.adapters.voice.livekit.FasterWhisperSTT")
@patch("app.adapters.voice.livekit.PiperTTS")
@patch("livekit.rtc.Room")
@patch("livekit.api.AccessToken")
def test_livekit_adapter_end_session(mock_access_token, mock_room, mock_tts, mock_stt, mock_env, adapter_config):
    adapter = LiveKitVoiceAdapter(config=adapter_config)
    adapter._session = VoiceSession(
        session_id="test-session",
        channel="voice",
        started_at="2024-01-01T00:00:00Z",
        status=SessionStatus.active
    )
    adapter._room = MagicMock()
    adapter._room.isconnected.return_value = True
    adapter._room.disconnect = AsyncMock()
    
    vc = adapter.end_session()
    
    
    adapter._room.disconnect.assert_called_once()
    assert vc.session.status.value == "completed"

def test_livekit_adapter_is_agent(adapter_config):
    import livekit.rtc
    adapter = LiveKitVoiceAdapter(config=adapter_config)
    
    # We must access _is_agent which is nested inside start_session now, or test the logic
    # Since _is_agent is nested inside start_session, we can extract the logic out or just test the behavior
    # But since it's nested, testing it indirectly via participant_connected or remote_participants loop is best.
    pass

@patch("app.adapters.voice.livekit.FasterWhisperSTT")
@patch("app.adapters.voice.livekit.PiperTTS")
@patch("livekit.rtc.Room")
@patch("livekit.api.AccessToken")
@patch("livekit.api.LiveKitAPI")
@patch("livekit.rtc.AudioStream")
def test_livekit_adapter_agent_detection(mock_audio_stream, mock_livekit_api, mock_access_token, mock_room, mock_tts, mock_stt, mock_env, adapter_config):
    import livekit.rtc
    adapter = LiveKitVoiceAdapter(config=adapter_config)
    
    mock_room_instance = MagicMock()
    mock_room_instance.connect = AsyncMock()
    mock_room_instance.local_participant = MagicMock()
    mock_room_instance.local_participant.publish_track = AsyncMock()
    
    # 1. Test ParticipantKind.AGENT with dynamic identity
    p1 = MagicMock(spec=livekit.rtc.RemoteParticipant)
    p1.kind = livekit.rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
    p1.identity = "agent-1234"
    p1.name = ""
    
    # 2. Test identity == agent_name
    p2 = MagicMock(spec=livekit.rtc.RemoteParticipant)
    p2.kind = livekit.rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD
    p2.identity = "my-agent"
    p2.name = ""
    
    # 3. Test name == agent_name
    p3 = MagicMock(spec=livekit.rtc.RemoteParticipant)
    p3.kind = livekit.rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD
    p3.identity = "random"
    p3.name = "my-agent"
    
    # 4. Test normal participant
    p4 = MagicMock(spec=livekit.rtc.RemoteParticipant)
    p4.kind = livekit.rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD
    p4.identity = "user-123"
    p4.name = "User"
    
    # Mock an audio track for p1 to pass the track wait check
    mock_track = MagicMock()
    mock_track.kind = livekit.rtc.TrackKind.KIND_AUDIO
    mock_pub = MagicMock()
    mock_pub.subscribed = True
    mock_pub.track = mock_track
    p1.track_publications = {"track-1": mock_pub}
    
    mock_room_instance.remote_participants = {"p1": p1, "p2": p2, "p3": p3, "p4": p4}
    mock_room.return_value = mock_room_instance
    
    # Mock LiveKitAPI and AccessToken to prevent actual calls
    mock_api_instance = AsyncMock()
    mock_api_instance.agent_dispatch.create_dispatch = AsyncMock()
    mock_api_instance.__aenter__.return_value = mock_api_instance
    mock_api_instance.__aexit__.return_value = None
    mock_livekit_api.return_value = mock_api_instance
    
    mock_token_instance = MagicMock()
    mock_token_instance.with_identity.return_value = mock_token_instance
    mock_token_instance.with_name.return_value = mock_token_instance
    mock_token_instance.with_grants.return_value = mock_token_instance
    mock_token_instance.to_jwt.return_value = "fake_jwt"
    mock_access_token.return_value = mock_token_instance

    def _simulate_connect(*args, **kwargs):
        # We manually trigger the loop in start_session by not setting events,
        # but the check loop at the end of start_session will find p1 (the first agent)
        # and set the event!
        pass
        
    mock_room_instance.connect.side_effect = _simulate_connect
    
    with patch("livekit.rtc.LocalAudioTrack.create_audio_track"):
        adapter.start_session()
        
    # If the logic works, p1 should have triggered the agent_joined_event
    assert adapter._agent_participant == p1


def test_livekit_adapter_send_audio_resampling(adapter_config, tmp_path):
    import wave
    import struct
    adapter = LiveKitVoiceAdapter(config=adapter_config)
    adapter._session = MagicMock()
    adapter._session_dir = tmp_path
    adapter._save_audio = MagicMock()
    adapter._stt = MagicMock()
    adapter._stt.transcribe.return_value = "Test transcript"
    
    adapter._audio_source = MagicMock()
    adapter._audio_source.capture_frame = AsyncMock()
    
    # Generate 22050 Hz WAV
    wav_path = tmp_path / "test_22050.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        # 10 samples
        wf.writeframes(struct.pack("<10h", *range(10)))
        
    audio_bytes = wav_path.read_bytes()
    
    adapter.send_audio(audio_bytes, 0)
    
    # Should capture resampled audio (16000 Hz)
    adapter._audio_source.capture_frame.assert_called_once()
    frame = adapter._audio_source.capture_frame.call_args[0][0]
    
    assert frame.sample_rate == 16000
    assert frame.num_channels == 1
    assert len(frame.data) > 0

@patch("app.adapters.voice.livekit.FasterWhisperSTT")
@patch("app.adapters.voice.livekit.PiperTTS")
@patch("livekit.rtc.Room")
@patch("livekit.api.AccessToken")
@patch("livekit.api.LiveKitAPI")
def test_livekit_adapter_relay_and_timeout(mock_livekit_api, mock_access_token, mock_room, mock_tts, mock_stt, mock_env, adapter_config):
    import livekit.rtc
    adapter_config["ice_transport"] = "relay"
    adapter_config["connect_timeout"] = 15.0
    adapter = LiveKitVoiceAdapter(config=adapter_config)
    
    mock_room_instance = MagicMock()
    mock_room_instance.connect = AsyncMock()
    mock_room_instance.local_participant = MagicMock()
    mock_room_instance.local_participant.publish_track = AsyncMock()
    mock_room_instance.remote_participants = {}
    mock_room.return_value = mock_room_instance
    
    def simulate_agent_join(*args, **kwargs):
        adapter._agent_joined_event.set()
        adapter._agent_track_subscribed_event.set()
        return None
    mock_room_instance.connect.side_effect = simulate_agent_join
    
    mock_api_instance = AsyncMock()
    mock_api_instance.agent_dispatch.create_dispatch = AsyncMock()
    mock_api_instance.__aenter__.return_value = mock_api_instance
    mock_api_instance.__aexit__.return_value = None
    mock_livekit_api.return_value = mock_api_instance

    with patch("livekit.rtc.LocalAudioTrack.create_audio_track"):
        adapter.start_session()
        
    mock_room_instance.connect.assert_called_once()
    
    # Verify connect was called with custom options
    call_kwargs = mock_room_instance.connect.call_args[1]
    assert "options" in call_kwargs
    options = call_kwargs["options"]
    assert isinstance(options, livekit.rtc.RoomOptions)
    
    # Verify timeout
    assert options.connect_timeout == 15.0
    
    # Verify relay config
    assert options.rtc_config is not None
    assert options.rtc_config.ice_transport_type == livekit.rtc.IceTransportType.TRANSPORT_RELAY

@patch("app.adapters.voice.livekit.FasterWhisperSTT")
@patch("app.adapters.voice.livekit.PiperTTS")
@patch("livekit.rtc.Room")
@patch("livekit.api.AccessToken")
@patch("livekit.api.LiveKitAPI")
def test_livekit_adapter_timeout_only(mock_livekit_api, mock_access_token, mock_room, mock_tts, mock_stt, mock_env, adapter_config):
    import livekit.rtc
    adapter_config["connect_timeout"] = 15.0
    adapter = LiveKitVoiceAdapter(config=adapter_config)
    
    mock_room_instance = MagicMock()
    mock_room_instance.connect = AsyncMock()
    mock_room_instance.local_participant = MagicMock()
    mock_room_instance.local_participant.publish_track = AsyncMock()
    mock_room_instance.remote_participants = {}
    mock_room.return_value = mock_room_instance
    
    def simulate_agent_join(*args, **kwargs):
        adapter._agent_joined_event.set()
        adapter._agent_track_subscribed_event.set()
        return None
    mock_room_instance.connect.side_effect = simulate_agent_join
    
    mock_api_instance = AsyncMock()
    mock_api_instance.agent_dispatch.create_dispatch = AsyncMock()
    mock_api_instance.__aenter__.return_value = mock_api_instance
    mock_api_instance.__aexit__.return_value = None
    mock_livekit_api.return_value = mock_api_instance

    with patch("livekit.rtc.LocalAudioTrack.create_audio_track"):
        adapter.start_session()
        
    mock_room_instance.connect.assert_called_once()
    
    call_kwargs = mock_room_instance.connect.call_args[1]
    options = call_kwargs["options"]
    
    # Verify timeout is set, but rtc_config is NOT relay (default behavior preserved)
    assert options.connect_timeout == 15.0
    assert options.rtc_config is None

def test_livekit_adapter_receive_audio_vad_timeout(adapter_config, tmp_path):
    """
    REGRESSION TEST:
    Verifies that receive_audio does NOT wait the full 30s timeout if the agent is streaming
    silence or background noise. The RMS-based VAD should detect silence and break the loop.
    """
    adapter = LiveKitVoiceAdapter(config=adapter_config)
    adapter._session = MagicMock()
    adapter._session_dir = tmp_path
    adapter._save_audio = MagicMock()
    adapter._stt = MagicMock()
    adapter._stt.transcribe.return_value = "Test transcript"
    
    # Simulate that we are capturing some noise
    # We set _is_agent_speaking to True as if some noise > 200 RMS happened
    adapter._is_agent_speaking = True
    
    # We simulate that the LAST time it was actually speech was 2 seconds ago
    import time
    adapter._last_speech_time = time.time() - 2.0
    
    # And we fill the buffer with some fake PCM data
    adapter._agent_audio_buffer.extend(b"\x00\x00" * 16000)
    
    t_start = time.time()
    # Call receive_audio with a 10s timeout
    adapter.receive_audio(timeout_seconds=10.0)
    duration = time.time() - t_start
    
    assert duration < 1.0, f"receive_audio took {duration}s, expected it to break immediately on VAD silence"

def test_livekit_transcription_events_become_evidence(mock_env, adapter_config, tmp_path):
    """
    REGRESSION TEST:
    Verifies that when LiveKit produces user and agent transcript events natively,
    they are converted into VoiceTurn objects so the final ExecutionResult contains conversation evidence.
    """
    import livekit.rtc
    from app.adapters.voice.livekit import LiveKitVoiceAdapter
    from app.models.voice import Speaker
    from app.voice.converter import voice_to_normalized_conversation
    
    adapter = LiveKitVoiceAdapter(config=adapter_config)
    adapter._session = MagicMock()
    adapter._session.session_id = "test-session"
    adapter._session_dir = tmp_path
    
    # Mock room and participants
    adapter._room = MagicMock()
    adapter._room.local_participant = MagicMock()
    adapter._room.local_participant.publish_track = AsyncMock()
    agent_participant = MagicMock()
    agent_participant.kind = livekit.rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
    adapter._room.remote_participants = {"agent-1": agent_participant}
    
    # We need to manually invoke the on_transcription_received handler that is registered in start_session.
    # Since we can't easily grab the closure, we simulate the logic directly, OR we can extract it.
    # The actual bug fix was to capture transcription segments into _turns.
    
    # Simulate the transcription event
    agent_segment = MagicMock()
    agent_segment.final = True
    agent_segment.participant_identity = "agent-1"
    agent_segment.text = "Hello I am the agent"
    
    user_segment = MagicMock()
    user_segment.final = True
    user_segment.participant_identity = "local-user" # not in remote_participants
    user_segment.text = "I need a refund"
    
    transcription = MagicMock()
    transcription.segments = [agent_segment, user_segment]
    
    # To test the actual code, we must extract the handler. 
    # Let's mock start_session so we can grab the registered handler!
    handler_ref = []
    def mock_on(event_name):
        def decorator(func):
            if event_name == "transcription_received":
                handler_ref.append(func)
            return func
        return decorator
        
    adapter._room.on = mock_on
    
    # Mock out the parts of start_session that do async stuff
    with patch("livekit.rtc.LocalAudioTrack.create_audio_track"), \
         patch("livekit.api.LiveKitAPI"), \
         patch("livekit.api.AccessToken") as mock_token, \
         patch("livekit.rtc.Room", return_value=adapter._room):
        
        # Avoid the agent wait loop
        def set_joined(*args, **kwargs):
            adapter._agent_joined_event.set()
            adapter._agent_track_subscribed_event.set()
        
        mock_token_instance = MagicMock()
        mock_token_instance.with_identity.return_value = mock_token_instance
        mock_token_instance.with_name.return_value = mock_token_instance
        mock_token_instance.with_grants.return_value = mock_token_instance
        mock_token_instance.to_jwt.return_value = "fake_jwt"
        mock_token.return_value = mock_token_instance
        
        # Since adapter._room is partially mocked but it calls real FFI code for connect,
        # we should mock connect completely.
        adapter._room.connect = AsyncMock(side_effect=set_joined)
        
        adapter.start_session()
        
    assert handler_ref, "transcription_received handler not registered"
    transcription_handler = handler_ref[0]
    
    # Fire the event
    transcription_handler(transcription)
    
    # Get the conversation
    vc = adapter.get_conversation()
    
    # Verify VoiceTurns are created
    assert len(vc.turns) == 2
    assert vc.turns[0].speaker == Speaker.agent
    assert vc.turns[0].text == "Hello I am the agent"
    assert vc.turns[1].speaker == Speaker.user
    assert vc.turns[1].text == "I need a refund"
    
    # Verify the normalized conversation has the evidence
    normalized = voice_to_normalized_conversation(vc)
    assert len(normalized.messages) == 2
    assert normalized.messages[0].role == "agent"
    assert normalized.messages[1].role == "simulated_user"

