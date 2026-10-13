"""
Microphone recording and playback utility.

Encapsulates sounddevice and numpy dependencies to keep them lazy, ensuring
headless environments or CI runners without audio hardware don't crash during import.
"""

from __future__ import annotations

import io
import logging
import wave
from typing import Optional

logger = logging.getLogger(__name__)


class VoiceRecorder:
    """
    Handles local microphone recording and audio playback.
    """
    def __init__(
        self,
        sample_rate: int = 16_000,
        channels: int = 1,
        silence_duration: float = 1.0,
        max_recording_duration: float = 30.0,
        minimum_speech_duration: float = 0.3,
        vad_threshold: float = 300.0
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.silence_duration = silence_duration
        self.max_recording_duration = max_recording_duration
        self.minimum_speech_duration = minimum_speech_duration
        self.vad_threshold = vad_threshold
        
        self._sd = None
        self._np = None

    def _ensure_deps(self) -> None:
        if self._sd is None or self._np is None:
            try:
                import sounddevice as sd
                import numpy as np
                self._sd = sd
                self._np = np
            except ImportError as e:
                raise ImportError(
                    "Recording/playback requires 'sounddevice' and 'numpy'. "
                    "Install via: pip install sounddevice numpy"
                ) from e

    def record_audio(self, duration_seconds: float = 5.0, use_vad: bool = True) -> bytes:
        """
        Record audio from the default microphone.
        If use_vad is True, records until silence is detected after speech, up to max_recording_duration.
        Otherwise, records for a fixed duration of duration_seconds.
        Returns the recorded audio wrapped in a WAV container bytes.
        """
        self._ensure_deps()
        
        if not use_vad:
            logger.info(f"Recording for {duration_seconds} seconds...")
            try:
                recording = self._sd.rec(
                    int(duration_seconds * self.sample_rate),
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype='int16'
                )
                self._sd.wait()
                logger.info("Recording complete.")
            except Exception as e:
                raise RuntimeError(f"Microphone recording failed: {e}") from e
        else:
            logger.info("Listening... (speak, then pause to stop)")
            frames = []
            chunk_duration = 0.1
            chunk_samples = int(self.sample_rate * chunk_duration)
            
            has_spoken = False
            speech_time = 0.0
            silence_time = 0.0
            total_time = 0.0
            
            try:
                with self._sd.InputStream(samplerate=self.sample_rate, channels=self.channels, dtype='int16') as stream:
                    while total_time < self.max_recording_duration:
                        chunk, overflowed = stream.read(chunk_samples)
                        frames.append(chunk)
                        
                        # Calculate RMS for Voice Activity Detection
                        rms = self._np.sqrt(self._np.mean(chunk.astype(self._np.float32)**2))
                        
                        if rms > self.vad_threshold:
                            speech_time += chunk_duration
                            silence_time = 0.0
                            if speech_time >= self.minimum_speech_duration:
                                has_spoken = True
                        else:
                            if has_spoken:
                                silence_time += chunk_duration
                                
                        total_time += chunk_duration
                        
                        if has_spoken and silence_time >= self.silence_duration:
                            break
                            
                recording = self._np.concatenate(frames, axis=0)
                logger.info("Recording complete.")
            except Exception as e:
                raise RuntimeError(f"Microphone VAD recording failed: {e}") from e

        # Convert raw numpy array to WAV bytes
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16-bit = 2 bytes
            wf.setframerate(self.sample_rate)
            wf.writeframes(recording.tobytes())
            
        return buf.getvalue()

    def play_audio(self, wav_bytes: bytes) -> None:
        """
        Play a WAV format byte string through the default speaker.
        """
        self._ensure_deps()
        
        try:
            buf = io.BytesIO(wav_bytes)
            with wave.open(buf, "rb") as wf:
                sample_rate = wf.getframerate()
                channels = wf.getnchannels()
                frames = wf.readframes(wf.getnframes())
                
            # Convert frames to numpy array
            audio_array = self._np.frombuffer(frames, dtype=self._np.int16)
            
            logger.info("Playing audio response...")
            self._sd.play(audio_array, samplerate=sample_rate)
            self._sd.wait()
        except Exception as e:
            logger.error(f"Failed to play audio: {e}")
            raise
