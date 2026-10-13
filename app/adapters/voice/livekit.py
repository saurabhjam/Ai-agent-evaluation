"""
LiveKit Voice Adapter.

Connects to a real LiveKit voice agent using WebRTC.
Implements the synchronous VoiceAdapter interface by managing an internal event loop.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
import threading
import time
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import livekit.api
import livekit.rtc

from app.adapters.voice.base import VoiceAdapter, VoiceAdapterCapabilities
from app.adapters.voice.local import FasterWhisperSTT, PiperTTS
from app.models.voice import (
    HandoffEvent,
    SessionStatus,
    Speaker,
    ToolCall,
    ToolResult,
    VoiceConversation,
    VoiceEvent,
    VoiceEventType,
    VoiceSession,
    VoiceTurn,
)

logger = logging.getLogger(__name__)

_DEFAULT_SAMPLE_RATE = 16_000


class LiveKitVoiceAdapterCapabilities(VoiceAdapterCapabilities):
    supports_audio_recording: bool = True
    supports_latency_measurement: bool = True
    supports_interruption_detection: bool = False
    supports_tool_calls: bool = False
    supports_handoff_detection: bool = False
    supports_real_time_streaming: bool = True
    supports_telephony: bool = False


class LiveKitVoiceAdapter(VoiceAdapter):
    """
    Connects to a LiveKit voice agent via WebRTC.
    """

    def __init__(self, config: Optional[dict[str, Any]] = None):
        self.config = config or {}
        
        # Read LiveKit credentials from environment
        self._url = os.environ.get("LIVEKIT_URL")
        self._api_key = os.environ.get("LIVEKIT_API_KEY")
        self._api_secret = os.environ.get("LIVEKIT_API_SECRET")

        if not self._url or not self._api_key or not self._api_secret:
            raise ValueError(
                "LiveKit credentials missing. Ensure LIVEKIT_URL, LIVEKIT_API_KEY, "
                "and LIVEKIT_API_SECRET are set in the environment."
            )

        self._agent_name = self.config.get("agent_name", "my-agent")
        self._audio_dir = Path(self.config.get("audio_dir", "artifacts/voice"))
        self._sample_rate: int = int(self.config.get("sample_rate", _DEFAULT_SAMPLE_RATE))
        self._timeout: float = float(self.config.get("timeout", 30.0))
        self._connect_timeout: Optional[float] = None
        if "connect_timeout" in self.config:
            self._connect_timeout = float(self.config["connect_timeout"])
        self._ice_transport: str = self.config.get("ice_transport", "all")

        # We need TTS/STT just like LocalVoiceAdapter to send text and process agent audio
        tts_cfg = self.config.get("tts", {})
        stt_cfg = self.config.get("stt", {})
        self._tts = PiperTTS(
            voice=tts_cfg.get("voice", "en_US-lessac-medium"),
            model_path=tts_cfg.get("model_path"),
        )
        self._stt = FasterWhisperSTT(
            model_size=stt_cfg.get("model", "small"),
            device=stt_cfg.get("device", "cpu"),
            compute_type=stt_cfg.get("compute_type", "int8"),
            language=stt_cfg.get("language"),
        )

        self._session: Optional[VoiceSession] = None
        self._session_dir: Optional[Path] = None
        self._turns: list[VoiceTurn] = []
        self._events: list[VoiceEvent] = []
        self._tool_calls: list[ToolCall] = []
        self._tool_results: list[ToolResult] = []
        self._handoff_events: list[HandoffEvent] = []
        self._turn_index: int = 0

        # LiveKit specific state
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

        self._room = None
        self._audio_source: Optional[livekit.rtc.AudioSource] = None
        self._local_audio_track: Optional[livekit.rtc.LocalAudioTrack] = None
        
        self._agent_participant: Optional[livekit.rtc.RemoteParticipant] = None
        self._agent_audio_stream: Optional[livekit.rtc.AudioStream] = None
        
        # Audio capturing state
        self._agent_audio_buffer = bytearray()
        self._agent_audio_lock = threading.Lock()
        self._is_agent_speaking = False
        self._last_speech_time = 0.0
        
        # Events for synchronization
        self._agent_joined_event = threading.Event()
        self._agent_track_subscribed_event = threading.Event()

    @property
    def capabilities(self) -> LiveKitVoiceAdapterCapabilities:
        return LiveKitVoiceAdapterCapabilities()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_coro_sync(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=self._timeout)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start_session(self, config: Optional[dict[str, Any]] = None) -> str:
        session_id = str(uuid.uuid4())
        self._session = VoiceSession(
            session_id=session_id,
            channel="voice",
            started_at=datetime.now(timezone.utc).isoformat(),
            status=SessionStatus.active,
        )
        self._session_dir = self._audio_dir / session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"[LiveKitVoiceAdapter] Starting session: {session_id}")
        self._record_event(VoiceEventType.call_started)

        # 1. Generate token
        token = (
            livekit.api.AccessToken(self._api_key, self._api_secret)
            .with_identity(f"evaluator-{session_id}")
            .with_name("Evaluator")
            .with_grants(livekit.api.VideoGrants(
                room_join=True,
                room=f"room-{session_id}",
            ))
            .to_jwt()
        )

        # 2. Setup room event handlers
        def _is_agent(p: livekit.rtc.RemoteParticipant) -> bool:
            return (
                p.kind == livekit.rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
                or p.identity == self._agent_name
                or p.name == self._agent_name
            )

        async def _init_and_connect():
            self._room = livekit.rtc.Room(loop=self._loop)
            
            @self._room.on("participant_connected")
            def on_participant_connected(participant: livekit.rtc.RemoteParticipant):
                logger.info(f"Participant connected: {participant.identity} (name: {participant.name}, kind: {participant.kind})")
                if _is_agent(participant):
                    self._agent_participant = participant
                    self._agent_joined_event.set()

            @self._room.on("track_subscribed")
            def on_track_subscribed(track: livekit.rtc.RemoteTrack, publication: livekit.rtc.RemoteTrackPublication, participant: livekit.rtc.RemoteParticipant):
                logger.info(f"Track subscribed: {track.name} from {participant.identity}")
                if track.kind == livekit.rtc.TrackKind.KIND_AUDIO:
                    self._start_audio_capture(track)
                    self._agent_track_subscribed_event.set()
                    
            @self._room.on("transcription_received")
            def on_transcription_received(transcription: livekit.rtc.Transcription):
                logger.info(f"Transcription received: {transcription}")
                for segment in transcription.segments:
                    if segment.final:
                        # Identify speaker from participant identity if possible
                        participant = self._room.remote_participants.get(segment.participant_identity)
                        speaker = Speaker.agent if (participant and _is_agent(participant)) else Speaker.user
                        
                        self._turns.append(VoiceTurn(
                            speaker=speaker,
                            text=segment.text,
                            latency_ms=None,
                            audio_path=None
                        ))

            room_name = f"room-{session_id}"

            # Explicitly dispatch the configured agent
            from livekit.api import LiveKitAPI, CreateAgentDispatchRequest
            
            try:
                async with LiveKitAPI(
                    self._url,
                    self._api_key,
                    self._api_secret,
                ) as api:
                    await api.agent_dispatch.create_dispatch(
                        CreateAgentDispatchRequest(
                            agent_name=self._agent_name,
                            room=room_name,
                        )
                    )
                logger.info(
                    "Dispatched agent '%s' to room '%s'",
                    self._agent_name,
                    room_name,
                )
            except Exception:
                logger.exception(
                    "Failed to dispatch agent '%s' to room '%s'",
                    self._agent_name,
                    room_name,
                )
                raise

            # Configure ICE Transport and Room Options
            options_kwargs = {}
            if self._connect_timeout is not None:
                options_kwargs["connect_timeout"] = self._connect_timeout

            if self._ice_transport.lower() == "relay":
                logger.info("LiveKit ICE transport: RELAY")
                rtc_config = livekit.rtc.RtcConfiguration(
                    ice_transport_type=livekit.rtc.IceTransportType.TRANSPORT_RELAY
                )
                options_kwargs["rtc_config"] = rtc_config
            else:
                logger.info("LiveKit ICE transport: ALL")

            options = livekit.rtc.RoomOptions(**options_kwargs)

            # 3. Connect to room
            await self._room.connect(self._url, token, options=options)

            # Setup Local Audio Source & Track
            self._audio_source = livekit.rtc.AudioSource(self._sample_rate, 1)
            self._local_audio_track = livekit.rtc.LocalAudioTrack.create_audio_track(
                "eval_audio", self._audio_source
            )
            options = livekit.rtc.TrackPublishOptions(source=livekit.rtc.TrackSource.SOURCE_MICROPHONE)
            await self._room.local_participant.publish_track(self._local_audio_track, options)

        self._run_coro_sync(_init_and_connect())

        # Check if agent is already in the room
        for p in self._room.remote_participants.values():
            if _is_agent(p):
                self._agent_participant = p
                self._agent_joined_event.set()
                # Check for existing audio track
                for pub in p.track_publications.values():
                    if pub.subscribed and pub.track.kind == livekit.rtc.TrackKind.KIND_AUDIO:
                        self._start_audio_capture(pub.track)
                        self._agent_track_subscribed_event.set()
                break

        logger.info(f"Waiting for agent '{self._agent_name}' to join...")
        agent_joined = self._agent_joined_event.wait(timeout=self._timeout)
        if not agent_joined:
            raise TimeoutError(f"Timed out waiting for agent '{self._agent_name}' to join the LiveKit room.")
        
        logger.warning("[VOICE DEBUG 7] agent participant detected")
        logger.info(f"Waiting for agent audio track...")
        # Give some time for track subscription
        track_subscribed = self._agent_track_subscribed_event.wait(timeout=self._timeout)
        if not track_subscribed:
            raise TimeoutError(f"Timed out waiting for agent '{self._agent_name}' audio track to be subscribed.")

        return session_id

    def _start_audio_capture(self, track: livekit.rtc.RemoteTrack):
        self._agent_audio_stream = livekit.rtc.AudioStream(track, loop=self._loop)
        
        async def _capture_task():
            import audioop
            import time
            frame_count = 0
            logger.info(f"[_capture_task] Started capturing from track {track.sid}")
            try:
                async for event in self._agent_audio_stream:
                    if event.frame:
                        frame_count += 1
                        if frame_count % 100 == 0:
                            logger.info(f"[_capture_task] Captured {frame_count} frames. Sample rate: {event.frame.sample_rate}, channels: {event.frame.num_channels}")
                        
                        pcm_data = event.frame.data
                        # Convert memoryview to bytes. In livekit python SDK, 
                        # sometimes memoryview of ctypes needs careful handling.
                        # We will use bytes() directly to be safe.
                        try:
                            pcm_bytes = bytes(pcm_data)
                            rms = audioop.rms(pcm_bytes, 2)
                        except Exception as e:
                            logger.error(f"[_capture_task] RMS error: {e}")
                            continue

                        with self._agent_audio_lock:
                            self._agent_audio_buffer.extend(pcm_bytes)
                            if rms > 200:  # Threshold for speech in 16-bit PCM
                                self._is_agent_speaking = True
                                self._last_speech_time = time.time()
            except Exception as e:
                logger.error(f"[_capture_task] Failed with exception: {e}", exc_info=True)
                        
        asyncio.run_coroutine_threadsafe(_capture_task(), self._loop)

    def end_session(self) -> VoiceConversation:
        if self._session is None:
            raise RuntimeError("end_session() called before start_session()")
        
        if self._room.isconnected():
            self._run_coro_sync(self._room.disconnect())
        
        self._session.ended_at = datetime.now(timezone.utc).isoformat()
        self._session.status = SessionStatus.completed
        self._record_event(VoiceEventType.call_ended)
        logger.info(f"[LiveKitVoiceAdapter] Session ended: {self._session.session_id}")
        return self.get_conversation()

    # ------------------------------------------------------------------
    # Audio I/O
    # ------------------------------------------------------------------

    def send_audio(self, audio_bytes: bytes, turn_index: int = 0) -> None:
        if self._session is None:
            raise RuntimeError("send_audio() called before start_session()")
        
        # 1. Parse WAV to get raw PCM
        with io.BytesIO(audio_bytes) as buf:
            with wave.open(buf, "rb") as wf:
                if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                    raise ValueError(f"Audio must be 16-bit mono PCM (got {wf.getnchannels()} channels, {wf.getsampwidth()} bytes/sample)")
                framerate = wf.getframerate()
                pcm_data = wf.readframes(wf.getnframes())
                
        # 2. Resample if necessary
        if framerate != self._sample_rate:
            try:
                import audioop
                pcm_data, _ = audioop.ratecv(pcm_data, 2, 1, framerate, self._sample_rate, None)
                logger.info(f"Resampled audio from {framerate} Hz to {self._sample_rate} Hz")
            except Exception as exc:
                logger.error(f"Failed to resample audio from {framerate} Hz to {self._sample_rate} Hz: {exc}")
                raise

        self._save_audio(audio_bytes, "user", turn_index)

        try:
            text = self._stt.transcribe(audio_bytes, self._sample_rate)
        except Exception as exc:
            logger.warning(f"[LiveKitVoiceAdapter] STT failed: {exc}")
            text = "[STT failed]"

        self._record_event(VoiceEventType.speech_started)
        self._turns.append(VoiceTurn(
            speaker=Speaker.user,
            text=text,
            audio_path=str(self._session_dir / f"user_{turn_index:03d}.wav"),
        ))

        # Clear agent audio buffer before speaking
        with self._agent_audio_lock:
            self._agent_audio_buffer.clear()
            self._is_agent_speaking = False
            self._last_speech_time = time.time()

        # Publish audio frame in 10ms chunks (standard for WebRTC)
        samples_per_10ms = self._sample_rate // 100
        bytes_per_10ms = samples_per_10ms * 2
        
        for i in range(0, len(pcm_data), bytes_per_10ms):
            chunk = pcm_data[i:i+bytes_per_10ms]
            if len(chunk) < bytes_per_10ms:
                chunk += b'\x00' * (bytes_per_10ms - len(chunk))
                
            frame = livekit.rtc.AudioFrame(
                data=chunk,
                sample_rate=self._sample_rate,
                num_channels=1,
                samples_per_channel=samples_per_10ms
            )
            self._run_coro_sync(self._audio_source.capture_frame(frame))
            time.sleep(0.01)  # Real-time pacing
            
        self._record_event(VoiceEventType.speech_ended)

    def receive_audio(self, timeout_seconds: float = 30.0) -> bytes:
        if self._session is None:
            raise RuntimeError("receive_audio() called before start_session()")
            
        self._record_event(VoiceEventType.response_started)
        t_start = time.perf_counter()

        # Wait for agent to start and stop speaking
        # This is a rudimentary VAD (Voice Activity Detection) based on buffer length changes
        # For a real implementation, we'd rely on LiveKit TurnDetector or silence detection
        
        logger.info("Waiting for agent to speak...")
        slept = 0.0
        while not self._is_agent_speaking and slept < timeout_seconds:
            time.sleep(0.1)
            slept += 0.1
            
        if not self._is_agent_speaking:
            logger.warning("Agent did not speak within timeout")
            agent_audio_bytes = bytes()
            latency_ms = timeout_seconds * 1000
        else:
            logger.info("Agent is speaking...")
            latency_ms = (time.perf_counter() - t_start) * 1000.0
            
            # Wait for silence
            silence_duration = 0.0
            while silence_duration < 1.5 and slept < timeout_seconds:
                with self._agent_audio_lock:
                    silence_duration = time.time() - self._last_speech_time
                time.sleep(0.1)
                slept += 0.1
                
            with self._agent_audio_lock:
                agent_audio_bytes = bytes(self._agent_audio_buffer)
                self._agent_audio_buffer.clear()
                self._is_agent_speaking = False

        # Convert raw PCM to WAV
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(48000) # LiveKit typically delivers 48kHz by default
            wf.writeframes(agent_audio_bytes)
        wav_bytes = buf.getvalue()

        try:
            agent_text = self._stt.transcribe(wav_bytes, 48000)
        except Exception as exc:
            logger.warning(f"[LiveKitVoiceAdapter] Agent STT failed: {exc}")
            agent_text = "[agent STT failed]"

        audio_path = self._save_audio(wav_bytes, "agent", self._turn_index)
        
        self._turns.append(VoiceTurn(
            speaker=Speaker.agent,
            text=agent_text,
            latency_ms=latency_ms,
            audio_path=str(audio_path),
        ))
        
        self._turn_index += 1
        self._record_event(VoiceEventType.response_completed)
        
        return wav_bytes

    def send_text(self, text: str, turn_index: int = 0) -> None:
        if self._session is None:
            raise RuntimeError("send_text() called before start_session()")
        try:
            audio_bytes = self._tts.synthesize(text)
        except Exception as exc:
            logger.error(f"[LiveKitVoiceAdapter] TTS failed: {exc}")
            raise
        self.send_audio(audio_bytes, turn_index=turn_index)
        user_turns = [t for t in self._turns if t.speaker == Speaker.user]
        if user_turns:
            user_turns[-1].text = text

    def receive_text(self, timeout_seconds: float = 30.0) -> str:
        self.receive_audio(timeout_seconds=timeout_seconds)
        agent_turns = [t for t in self._turns if t.speaker == Speaker.agent]
        if agent_turns:
            return agent_turns[-1].text
        return ""

    # ------------------------------------------------------------------
    # Evidence accessors
    # ------------------------------------------------------------------

    def get_transcript(self) -> list[VoiceTurn]:
        return list(self._turns)

    def get_events(self) -> list[VoiceEvent]:
        return list(self._events)

    def get_session(self) -> Optional[VoiceSession]:
        return self._session

    def get_conversation(self) -> VoiceConversation:
        if self._session is None:
            raise RuntimeError("get_conversation() called before start_session()")
        return VoiceConversation(
            session=self._session,
            turns=list(self._turns),
            events=list(self._events),
            tool_calls=list(self._tool_calls),
            tool_results=list(self._tool_results),
            handoff_events=list(self._handoff_events),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_event(self, event_type: VoiceEventType, data: Optional[dict] = None) -> None:
        self._events.append(VoiceEvent(event_type=event_type, data=data))

    def _save_audio(self, audio_bytes: bytes, speaker: str, index: int) -> Path:
        filename = f"{speaker}_{index:03d}.wav"
        path = self._session_dir / filename
        path.write_bytes(audio_bytes)
        return path
