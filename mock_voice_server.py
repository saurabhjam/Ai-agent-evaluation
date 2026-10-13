"""
Mock Voice Agent API Server.

Acts as the System Under Test (SUT) for local voice evaluation.
Receives user audio via HTTP multipart/form-data POST, transcribes it,
determines a simple deterministic response, synthesizes the response,
and returns the raw WAV bytes.
"""

import os
import io
import logging
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response

# Load environment variables from .env if present
PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# Set a fallback PIPER_MODEL_PATH if not defined in environment
if "PIPER_MODEL_PATH" not in os.environ:
    os.environ["PIPER_MODEL_PATH"] = str(PROJECT_ROOT / "models" / "en_US-lessac-medium.onnx")

# Reuse local STT and TTS providers, keeping them mocked/lazy
from app.adapters.voice.local import FasterWhisperSTT, PiperTTS

logger = logging.getLogger(__name__)

app = FastAPI(title="Mock Voice Agent API")

# Initialize lazily so module can be imported in tests without loading models immediately
stt_provider = FasterWhisperSTT()
tts_provider = PiperTTS()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "mock-voice-agent"}


@app.post("/api/voice")
async def process_voice(audio: UploadFile = File(...)):
    """
    Process incoming voice turn.
    Returns the agent's synthesized WAV response.
    """
    if not audio.filename:
        raise HTTPException(status_code=400, detail="Missing audio file.")
        
    try:
        audio_bytes = await audio.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file.")
            
        # 1. Transcribe User Audio
        try:
            transcript = stt_provider.transcribe(audio_bytes)
            logger.info(f"Transcribed User: {transcript}")
        except Exception as e:
            logger.error(f"STT Failed: {e}")
            raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

        # 2. Deterministic Mock Logic
        transcript_lower = transcript.lower()
        
        if "refund" in transcript_lower:
            agent_text = "I can help you with your refund request. Please provide the order details and describe the issue with the product."
        elif "damage" in transcript_lower or "damaged" in transcript_lower:
            agent_text = "Thank you for explaining the damage. I have recorded the issue and can continue with the refund request."
        elif "exit" in transcript_lower or "goodbye" in transcript_lower:
            agent_text = "Thank you for contacting us. Goodbye."
        else:
            agent_text = "I understand. Please tell me more about what you need help with."
            
        logger.info(f"Agent Response: {agent_text}")

        # 3. Synthesize Agent Audio
        try:
            response_wav = tts_provider.synthesize(agent_text)
        except Exception as e:
            logger.error(f"TTS Failed: {e}")
            raise HTTPException(status_code=500, detail=f"Synthesis failed: {e}")

        # 4. Return Raw WAV
        return Response(content=response_wav, media_type="audio/wav")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Internal error processing voice")
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


if __name__ == "__main__":
    import uvicorn
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001, help="Port to run the mock server on")
    args = parser.parse_args()
    
    print("\n========================================")
    print("MOCK VOICE AGENT")
    print(f"Listening on: http://127.0.0.1:{args.port}")
    print("========================================\n")
    
    uvicorn.run("mock_voice_server:app", host="127.0.0.1", port=args.port, log_level="info")
