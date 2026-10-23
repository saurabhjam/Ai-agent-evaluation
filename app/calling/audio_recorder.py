"""Provider-neutral, session-timeline recording for calling evaluations."""

from __future__ import annotations

from dataclasses import dataclass, field
import audioop
import io
from pathlib import Path
import threading
import time
import wave

from app.calling.models import CallArtifactType, CallProvider, CallRecording


_CAPTURE_ROOT = (Path(__file__).resolve().parents[2] / "artifacts" / "call" / "audio").resolve()


@dataclass(frozen=True)
class _Segment:
    start_frame: int
    pcm: bytes


@dataclass
class EvaluationAudioRecorder:
    """Capture normalized remote/local PCM on one monotonic session clock."""

    session_id: str
    sample_rate: int = 24_000
    channels: int = 1
    sample_width: int = 2
    clock: object = time.monotonic
    started_at: float = field(init=False)
    _segments: dict[str, list[_Segment]] = field(
        default_factory=lambda: {"agent": [], "persona": []}, init=False
    )
    _track_end: dict[str, int] = field(
        default_factory=lambda: {"agent": 0, "persona": 0}, init=False
    )
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        self.started_at = float(self.clock())

    def on_remote_audio(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int = 1,
        sample_width: int = 2,
        timestamp: float | None = None,
    ) -> None:
        self._append("agent", pcm, sample_rate, channels, sample_width, timestamp)

    def on_local_audio(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int = 1,
        sample_width: int = 2,
        timestamp: float | None = None,
    ) -> None:
        self._append("persona", pcm, sample_rate, channels, sample_width, timestamp)

    def finalize(self) -> CallRecording | None:
        with self._lock:
            segments = [segment for values in self._segments.values() for segment in values]
            if not segments:
                return None
            total_frames = max(
                segment.start_frame + len(segment.pcm) // self.sample_width
                for segment in segments
            )
            mixed = bytearray(total_frames * self.sample_width)
            for segment in segments:
                start = segment.start_frame * self.sample_width
                end = start + len(segment.pcm)
                mixed[start:end] = audioop.add(bytes(mixed[start:end]), segment.pcm, self.sample_width)

        _CAPTURE_ROOT.mkdir(parents=True, exist_ok=True)
        path = _CAPTURE_ROOT / f"{self.session_id}-full_call.wav"
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(self.channels)
            wav.setsampwidth(self.sample_width)
            wav.setframerate(self.sample_rate)
            wav.writeframes(bytes(mixed))
        payload = output.getvalue()
        if len(payload) <= 44:
            return None
        path.write_bytes(payload)
        return CallRecording(
            artifact_id="full_call",
            session_id=self.session_id,
            provider=CallProvider.custom,
            provider_name="evalforge",
            artifact_type=CallArtifactType.audio,
            recording_id=f"{self.session_id}-evalforge",
            path=str(path),
            content_type="audio/wav",
            duration_seconds=total_frames / self.sample_rate,
            channels=self.channels,
            format="wav",
            sample_rate=self.sample_rate,
            metadata={"source": "evalforge", "channel": "full"},
        )

    def _append(
        self,
        track: str,
        pcm: bytes,
        sample_rate: int,
        channels: int,
        sample_width: int,
        timestamp: float | None,
    ) -> None:
        normalized = _normalize_pcm(
            pcm,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
            target_rate=self.sample_rate,
        )
        if not normalized:
            return
        observed_at = float(self.clock()) if timestamp is None else timestamp
        observed_frame = max(int((observed_at - self.started_at) * self.sample_rate), 0)
        with self._lock:
            start_frame = max(observed_frame, self._track_end[track])
            self._segments[track].append(_Segment(start_frame, normalized))
            self._track_end[track] = start_frame + len(normalized) // self.sample_width


def _normalize_pcm(
    pcm: bytes,
    *,
    sample_rate: int,
    channels: int,
    sample_width: int,
    target_rate: int,
) -> bytes:
    if not pcm:
        return b""
    normalized = pcm
    if sample_width != 2:
        normalized = audioop.lin2lin(normalized, sample_width, 2)
        sample_width = 2
    if channels == 2:
        normalized = audioop.tomono(normalized, sample_width, 0.5, 0.5)
        channels = 1
    if channels != 1:
        raise ValueError(f"Unsupported audio channel count: {channels}")
    if sample_rate != target_rate:
        normalized, _ = audioop.ratecv(
            normalized, sample_width, channels, sample_rate, target_rate, None
        )
    return normalized
