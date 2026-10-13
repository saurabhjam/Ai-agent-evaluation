import json
import logging
import time
import wave
import struct
from pathlib import Path
from typing import Any, Optional

from app.schemas import Persona
from app.simulator import generate_next_user_turn
from app.models.voice import VoiceConversation
from app.voice.audio import trim_leading_silence, resample_pcm

logger = logging.getLogger(__name__)

class VoicePersonaEngine:
    """
    Automates an interactive voice conversation by acting as the simulated user.
    Uses the existing generation logic from `app.simulator.generate_next_user_turn`.
    """
    def __init__(
        self,
        persona: Persona,
        adapter: Any,
        tts_provider: Any,
        max_turns: int = 10,
        max_session_duration_seconds: int = 900
    ):
        self.persona = persona
        self.adapter = adapter
        self.tts = tts_provider
        self.max_turns = max_turns
        self.max_session_duration_seconds = max_session_duration_seconds
        
    def run_automated_session(self) -> VoiceConversation:
        logger.warning(f"[VOICE DEBUG 5] VoicePersonaEngine started. max_turns={self.max_turns} max_duration={self.max_session_duration_seconds}")
        session_id = self.adapter.start_session()
        logger.warning(f"[VOICE DEBUG 6] LiveKit session started: {session_id}")
        logger.info(f"Started automated voice persona session: {session_id}")
        
        start_time = time.time()
        turn_count = 0
        
        while turn_count < self.max_turns:
            logger.warning(f"[VOICE DEBUG 12] max turns/session check for turn {turn_count}/{self.max_turns}")
            time_left = self.max_session_duration_seconds - (time.time() - start_time)
            if time_left <= 0:
                logger.warning("Max session duration exceeded. Ending conversation.")
                break
                
            transcript = self.adapter.get_transcript()
            
            try:
                user_turn_data = generate_next_user_turn(self.persona, transcript)
                user_text = user_turn_data.get("message", "")
                logger.warning("[VOICE DEBUG 11] persona generated next message")
            except Exception as e:
                logger.error(f"Persona generation failed: {e}")
                break
                
            if not user_text or "[END_CONVERSATION]" in user_text:
                logger.info("Persona indicated goal completion or ended conversation.")
                break
                
            try:
                user_wav = self.tts.synthesize(user_text)
            except Exception as e:
                logger.error(f"TTS synthesis failed: {e}")
                break
                
            try:
                self.adapter.send_audio(user_wav, turn_index=turn_count)
                logger.warning("[VOICE DEBUG 8] user audio sent")
            except Exception as e:
                logger.exception(f"Adapter send_audio failed: {type(e).__name__}: {e}")
                break
                
            try:
                logger.warning(f"[VOICE DEBUG] Adapter waiting for audio with timeout={min(30.0, time_left)}")
                self.adapter.receive_audio(timeout_seconds=min(30.0, time_left))
                logger.warning("[VOICE DEBUG 9] agent audio received")
                logger.warning("[VOICE DEBUG 10] agent transcript received")
            except Exception as e:
                logger.error(f"Agent response failed or timed out: {e}")
                break
                
            turn_count += 1
            
        logger.warning("[VOICE DEBUG 13] voice session ending")
        res = self.adapter.end_session()
        logger.warning("[VOICE DEBUG 14] adapter.end_session completed")
        return res
        
    @staticmethod
    def generate_full_audio_and_json(vc: VoiceConversation, session_dir: Path, scenario_id: str) -> dict:
        """
        Merge all WAV files into one full_conversation.wav separated by ~300ms silence.
        Save conversation.json containing turn details and audio paths.
        """
        audio_files = []
        conversation_data = {
            "session_id": vc.session.session_id,
            "scenario_id": scenario_id,
            "turns": [],
            "full_audio_path": None
        }
        
        current_turn_index = 1
        for i, turn in enumerate(vc.turns):
            speaker_str = turn.speaker.value if hasattr(turn.speaker, 'value') else str(turn.speaker)
            
            turn_dict = {
                "turn": current_turn_index,
                "speaker": speaker_str,
                "text": turn.text,
                "audio_path": str(Path(turn.audio_path).name) if turn.audio_path else None,
            }
            conversation_data["turns"].append(turn_dict)
            
            if speaker_str == "agent":
                current_turn_index += 1
                
            if turn.audio_path and Path(turn.audio_path).exists():
                raw_path = Path(turn.audio_path)
                audio_to_merge = raw_path
                
                if speaker_str == "agent":
                    clean_path = raw_path.with_name(f"{raw_path.stem}_clean{raw_path.suffix}")
                    try:
                        raw_dur, silence_dur, clean_dur = trim_leading_silence(raw_path, clean_path)
                        turn_dict["audio_metadata"] = {
                            "raw_audio_path": raw_path.name,
                            "cleaned_audio_path": clean_path.name,
                            "raw_duration_ms": raw_dur,
                            "leading_silence_ms": silence_dur,
                            "cleaned_duration_ms": clean_dur
                        }
                        audio_to_merge = clean_path
                    except Exception as e:
                        logger.error(f"Failed to trim leading silence for {raw_path.name}: {e}")
                        
                audio_files.append(audio_to_merge)
                
        if not audio_files:
            return conversation_data
            
        full_audio_path = session_dir / "full_conversation.wav"
        try:
            # We hardcode 16000 Hz for the universal output format
            target_framerate = 16000
            
            # Read first file just to grab channels and sampwidth (usually mono 16-bit)
            with wave.open(str(audio_files[0]), "rb") as wf:
                nchannels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                
            silence_frames = int(target_framerate * 0.3)
            silence_bytes = struct.pack(f"<{silence_frames}h", *([0] * silence_frames))
            
            with wave.open(str(full_audio_path), "wb") as out_wf:
                out_wf.setnchannels(nchannels)
                out_wf.setsampwidth(sampwidth)
                out_wf.setframerate(target_framerate)
                
                for i, path in enumerate(audio_files):
                    with wave.open(str(path), "rb") as in_wf:
                        in_rate = in_wf.getframerate()
                        raw_frames = in_wf.readframes(in_wf.getnframes())
                        
                        if in_rate != target_framerate:
                            # Resample dynamically
                            resampled_frames = resample_pcm(
                                raw_frames, 
                                in_rate, 
                                target_framerate, 
                                sampwidth=sampwidth, 
                                channels=nchannels
                            )
                            out_wf.writeframes(resampled_frames)
                        else:
                            out_wf.writeframes(raw_frames)
                            
                    if i < len(audio_files) - 1:
                        out_wf.writeframes(silence_bytes)
                        
            conversation_data["full_audio_path"] = str(full_audio_path.absolute())
            
        except Exception as e:
            logger.error(f"Failed to merge audio files: {e}")
            
        json_path = session_dir / "conversation.json"
        json_path.write_text(json.dumps(conversation_data, indent=2))
        
        return conversation_data
