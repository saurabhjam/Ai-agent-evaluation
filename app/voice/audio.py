import wave
import struct
import math
import audioop
import math
from pathlib import Path
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

def trim_leading_silence(
    wav_path: Path, 
    output_path: Path, 
    threshold_rms: int = 50, 
    chunk_ms: int = 10,
    min_speech_ms: int = 100
) -> Tuple[int, int, int]:
    """
    Trims leading silence from a raw PCM WAV file based on RMS energy.
    Requires a continuous non-silent block to avoid triggering on clicks/pops.
    Does NOT trim trailing silence.
    
    Returns:
        Tuple[int, int, int]: (raw_duration_ms, leading_silence_ms, cleaned_duration_ms)
    """
    with wave.open(str(wav_path), 'rb') as wf:
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        nframes = wf.getnframes()
        
        raw_duration_ms = int(nframes / framerate * 1000)
        
        chunk_frames = int(framerate * chunk_ms / 1000)
        
        if sampwidth != 2:
            raise ValueError(f"Only 16-bit PCM is supported. Got {sampwidth*8}-bit.")
            
        speech_start_frame = nframes  # default to all silence
        consecutive_speech_chunks = 0
        required_consecutive_chunks = max(1, min_speech_ms // chunk_ms)
        
        current_frame = 0
        while current_frame < nframes:
            frames_to_read = min(chunk_frames, nframes - current_frame)
            data = wf.readframes(frames_to_read)
            if not data:
                break
                
            samples = struct.unpack(f"<{len(data)//2}h", data)
            
            # Compute RMS
            rms = math.sqrt(sum(s*s for s in samples) / len(samples)) if samples else 0
            
            if rms >= threshold_rms:
                consecutive_speech_chunks += 1
                if consecutive_speech_chunks >= required_consecutive_chunks:
                    # we found continuous speech
                    # the start of this continuous block is at (current_frame - (required_consecutive_chunks - 1) * chunk_frames)
                    speech_start_frame = max(0, current_frame - (required_consecutive_chunks - 1) * chunk_frames)
                    break
            else:
                consecutive_speech_chunks = 0
                
            current_frame += frames_to_read
            
        leading_silence_ms = int(speech_start_frame / framerate * 1000)
        cleaned_duration_ms = raw_duration_ms - leading_silence_ms
        
        # Now copy the remaining audio to the output file
        wf.setpos(speech_start_frame)
        with wave.open(str(output_path), 'wb') as out_wf:
            out_wf.setnchannels(nchannels)
            out_wf.setsampwidth(sampwidth)
            out_wf.setframerate(framerate)
            
            # Write remaining frames
            remaining_frames = nframes - speech_start_frame
            while remaining_frames > 0:
                chunk = min(1024 * 1024, remaining_frames) # read in large chunks
                data = wf.readframes(chunk)
                if not data:
                    break
                out_wf.writeframes(data)
                remaining_frames -= chunk
                
    return raw_duration_ms, leading_silence_ms, cleaned_duration_ms

def resample_pcm(pcm_data: bytes, in_rate: int, out_rate: int, sampwidth: int = 2, channels: int = 1) -> bytes:
    """
    Resamples PCM audio bytes from in_rate to out_rate.
    """
    if in_rate == out_rate:
        return pcm_data
        
    resampled, _ = audioop.ratecv(pcm_data, sampwidth, channels, in_rate, out_rate, None)
    return resampled
