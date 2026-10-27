"""Offline-only Whisper runtime benchmark; never creates a provider session."""
import argparse
import io
import json
import os
from pathlib import Path
import time
import wave
import audioop

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--output", required=True)
    parser.add_argument("--language", default=None)
    args = parser.parse_args()
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio

    root = Path(__file__).resolve().parents[1]
    source = root / "artifacts/eval_4eb7bce88b994fc8bc88c7bf4f96faf6/full_call.wav"
    snapshot = next((Path.home() / ".cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots").iterdir())
    start = time.perf_counter()
    model = WhisperModel(str(snapshot), device="cpu", compute_type="int8", cpu_threads=args.threads)
    result = {"threads": args.threads, "language": args.language, "model_ms": (time.perf_counter()-start)*1000, "clips": []}
    with wave.open(str(source), "rb") as wav:
        rate, width, channels = wav.getframerate(), wav.getsampwidth(), wav.getnchannels()
        pcm = wav.readframes(wav.getnframes())
    frame_bytes = rate//50 * width * channels
    onset = next(i for i in range(0, len(pcm), frame_bytes) if audioop.rms(pcm[i:i+frame_bytes], width) >= 60)
    # Same immutable recorded prefix for every configuration; longer clips include real pauses.
    for seconds in (1, 2, 5, 10):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setparams((channels, width, rate, 0, "NONE", "not compressed"))
            wav.writeframes(pcm[onset:onset+seconds*rate*width*channels])
        started = time.perf_counter()
        audio = decode_audio(io.BytesIO(buf.getvalue()))
        decoded = time.perf_counter()
        segments, info = model.transcribe(audio, beam_size=1, language=args.language)
        invoked = time.perf_counter()
        segments = list(segments)
        ended = time.perf_counter()
        row = {"seconds": seconds, "preprocessing_ms": (decoded-started)*1000,
               "invocation_ms": (invoked-decoded)*1000, "materialization_ms": (ended-invoked)*1000,
               "total_ms": (ended-started)*1000, "rtf": (ended-started)/seconds,
               "text": " ".join(s.text.strip() for s in segments)}
        result["clips"].append(row)
        print(json.dumps(row), flush=True)
        Path(args.output).write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
