"""Evaluator-side voice conversation runner for calling evaluations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional
import io
import logging
import time
import wave

from app.calling.models import (
    CallRecording,
    CallTranscriptTurn,
    RawCallTranscript,
    TranscriptSpeaker,
)
from app.calling.voice_transport import VoiceTransport, VoiceTransportSession
from app.schemas import Persona
from app.calling.simulator import generate_next_user_turn
from app.calling import diagnostics
from app.calling.audio_recorder import EvaluationAudioRecorder


logger = logging.getLogger(__name__)

SimulatorFn = Callable[[Persona, list[Any]], dict[str, Any]]


@dataclass
class VoiceConversationRunner:
    """
    Owns evaluator-side conversation lifecycle and turn-taking.

    VoiceTransport stays low-level: it creates/owns the media session. This
    runner owns the AI user simulator, STT/TTS handoff points, transcript
    assembly, and stop conditions.
    """

    simulator: SimulatorFn = generate_next_user_turn
    max_turns: int = 8
    receive_timeout_seconds: float = 30.0
    tts_provider: Optional[Any] = None
    stt_provider: Optional[Any] = None
    audio_recorder_factory: Callable[..., Any] = EvaluationAudioRecorder
    recordings: list[CallRecording] = field(default_factory=list, init=False)
    _turn_boundaries: dict[str, Any] = field(default_factory=dict, init=False)

    @diagnostics.traced_conversation
    def run(
        self,
        *,
        persona: Persona,
        transport: VoiceTransport,
        session: VoiceTransportSession,
        session_id: str,
        run_id: str,
    ) -> RawCallTranscript:
        turns: list[CallTranscriptTurn] = []
        simulator_contract_violations: list[dict[str, Any]] = []
        last_agent_text = ""
        latency_turns: list[dict[str, Any]] = []
        completion_reason: str | None = None
        self._last_stt_ms = 0.0
        lifecycle = {}

        self.recordings = []
        recorder = None
        try:
            recorder = self.audio_recorder_factory(session_id=session_id)
            transport.set_audio_recorder(recorder)
        except Exception:
            logger.exception("Unable to initialize EvalForge call recording; evaluation will continue")

        transport.connect(session)
        try:
            for turn_index in range(self.max_turns):
                diagnostics.begin_turn(turn_index)
                self._turn_boundaries = {
                    "clock_anchor_s": time.perf_counter(),
                    "clock_anchor_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                }
                with diagnostics.stage("agent.receive", "calling_runner"):
                    agent_text = self._receive_agent_text(transport)
                diagnostics.emit("agent.simulator_input", "runner_agent_text", {"text": agent_text})
                if not agent_text or agent_text == last_agent_text:
                    continue
                last_agent_text = agent_text
                turns.append(
                    CallTranscriptTurn(
                        speaker=TranscriptSpeaker.agent,
                        text=agent_text,
                        turn_index=len(turns),
                    )
                )

                with diagnostics.stage("simulator", "calling_runner"):
                    self._turn_boundaries["simulator_start_s"] = time.perf_counter()
                    user_turn = self.simulator(persona, turns)
                    self._turn_boundaries["simulator_end_s"] = time.perf_counter()
                user_text = (user_turn.get("message") or "").strip()
                spoken_text = (user_turn.get("spoken_message") or user_text).strip()
                contract = dict(user_turn.get("simulator_contract") or {})
                if contract and contract.get("valid") is False:
                    simulator_contract_violations.append({"turn_id": turn_index, **contract})
                if not user_text or "[END_CONVERSATION]" in user_text:
                    completion_reason = user_turn.get("completion_reason")
                    if completion_reason == "semantic_conversation_complete":
                        lifecycle["semantic_completion_at"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                        latency_turns.append({
                            "turn_id": turn_index, "first_turn": turn_index == 0,
                            "completion_reason": completion_reason,
                            "stt_ms": self._last_stt_ms,
                            "stt_details": self._stt_details(),
                            **dict(user_turn.get("timings") or {}),
                            "tts_ms": 0.0, "transport_ms": 0.0,
                            "time_to_first_persona_audio_ms": None,
                            "boundaries": dict(self._turn_boundaries),
                            **self._transport_receive_timing(transport),
                        })
                    break

                diagnostics.customer_text(user_text)
                tts_ms, transport_ms, first_audio_ms = self._send_user_text(
                    transport,
                    user_text,
                    spoken_text=spoken_text,
                    turn_index=turn_index,
                )
                turns.append(
                    CallTranscriptTurn(
                        speaker=TranscriptSpeaker.customer,
                        text=user_text,
                        turn_index=len(turns),
                        metadata={"simulator_contract": contract} if contract else {},
                    )
                )
                timing = {
                    "turn_id": turn_index,
                    "first_turn": turn_index == 0,
                    **dict(user_turn.get("timings") or {}),
                    "stt_ms": self._last_stt_ms,
                    "stt_details": self._stt_details(),
                    "tts_ms": tts_ms,
                    "transport_ms": transport_ms,
                }
                timing.update(self._transport_receive_timing(transport))
                timing["boundaries"] = dict(self._turn_boundaries)
                pre_send_ms = sum(
                    float(timing.get(key) or 0.0)
                    for key in (
                        "turn_end_detection_ms", "stt_ms", "intent_policy_ms",
                        "groq_ms", "grounding_ms",
                    )
                )
                timing["time_to_first_persona_audio_ms"] = pre_send_ms + first_audio_ms if first_audio_ms is not None else None
                timing["total_response_latency_ms"] = pre_send_ms + tts_ms + transport_ms
                origin = timing["receive_boundaries"].get("meaningful_audio_end_s")
                first_sent = self._turn_boundaries.get("first_frame_sent_s")
                final_sent = self._turn_boundaries.get("final_frame_sent_s")
                if origin is not None and first_sent is not None:
                    timing["time_to_first_persona_audio_ms"] = (first_sent - origin) * 1000
                if origin is not None and final_sent is not None:
                    timing["total_response_latency_ms"] = (final_sent - origin) * 1000
                latency_turns.append(timing)
                diagnostics.emit("turn.latency", "calling_runner", timing)
        finally:
            try:
                lifecycle["transport_close_start_at"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                transport.hang_up(session)
                lifecycle["transport_closed_at"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            finally:
                if recorder is not None:
                    try:
                        recording = recorder.finalize()
                        if recording is not None:
                            self.recordings.append(recording)
                        lifecycle["recorder_finalized_at"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                    except Exception:
                        logger.exception(
                            "Unable to finalize EvalForge call recording; evaluation will continue"
                        )
                lifecycle["runner_exit_at"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                diagnostics.emit("conversation.lifecycle", "calling_runner", lifecycle)

        return RawCallTranscript(
            session_id=session_id,
            run_id=run_id,
            turns=turns,
            source="voice_transport",
            metadata={
                "transport_name": session.transport_name,
                "transport_call_id": session.transport_call_id,
                "simulator_contract_violations": simulator_contract_violations,
                "completion_reason": completion_reason,
                "latency_turns": latency_turns,
                "conversation_lifecycle": lifecycle,
            },
        )

    def _send_user_text(
        self,
        transport: VoiceTransport,
        text: str,
        *,
        spoken_text: str,
        turn_index: int,
    ) -> tuple[float, float, float | None]:
        if hasattr(transport, "send_text"):
            diagnostics.emit("transport.text_input", "transport_send_text", {"text": text})
            started = time.perf_counter()
            transport.send_text(text, turn_index=turn_index)
            elapsed = (time.perf_counter() - started) * 1000
            return 0.0, elapsed, elapsed
        if not self.tts_provider or not hasattr(transport, "send_audio"):
            raise RuntimeError(
                f"{transport.__class__.__name__} cannot send evaluator speech; "
                "provide send_text() or send_audio() with a TTS provider."
            )
        tts_started = time.perf_counter()
        self._turn_boundaries["tts_start_s"] = tts_started
        with diagnostics.stage("tts", "tts_input", {"text": spoken_text}):
            audio = self.tts_provider.synthesize(spoken_text)
        tts_ms = (time.perf_counter() - tts_started) * 1000
        self._turn_boundaries["tts_complete_s"] = time.perf_counter()
        self._turn_boundaries["first_tts_audio_available_s"] = self._turn_boundaries["tts_complete_s"]
        send_started = time.perf_counter()
        with diagnostics.stage("customer.send", "transport_send_audio"):
            transport.send_audio(audio, turn_index=turn_index)
        transport_ms = (time.perf_counter() - send_started) * 1000
        send_timing = transport.last_send_timing() if hasattr(transport, "last_send_timing") else {}
        self._turn_boundaries.update(send_timing)
        delay = send_timing.get("first_frame_delay_ms")
        first_audio_ms = delay + tts_ms if delay is not None else None
        return tts_ms, transport_ms, first_audio_ms

    @staticmethod
    def _transport_receive_timing(transport: VoiceTransport) -> dict[str, Any]:
        timing = transport.last_receive_timing() if hasattr(transport, "last_receive_timing") else {}
        return {
            "turn_end_detection_ms": timing.get("turn_end_detection_ms"),
            "agent_audio_duration_ms": timing.get("agent_audio_duration_ms"),
            "receive_boundaries": timing,
        }

    def _stt_details(self) -> dict[str, Any]:
        details = getattr(self.stt_provider, "last_transcription_timing", None)
        return dict(details) if isinstance(details, dict) else {}

    def _receive_agent_text(self, transport: VoiceTransport) -> str:
        if hasattr(transport, "receive_text"):
            return str(transport.receive_text(timeout_seconds=self.receive_timeout_seconds) or "").strip()
        if not hasattr(transport, "receive_audio"):
            return ""
        control_snapshot = diagnostics.control_snapshot(transport)
        with diagnostics.stage("audio.receive", "transport_receive_audio"):
            try:
                audio = transport.receive_audio(timeout_seconds=self.receive_timeout_seconds)
                self._turn_boundaries["receive_return_s"] = time.perf_counter()
            finally:
                diagnostics.observe_controls(control_snapshot)
        completion_check = getattr(transport, "last_utterance_complete", None)
        utterance_complete = completion_check() if callable(completion_check) else True
        if (
            not utterance_complete
            and getattr(self.simulator, "allow_incomplete_utterance", False) is not True
        ):
            diagnostics.emit("agent.incomplete", "transport_receive_audio", None)
            return ""
        info = _audio_info(audio)
        logger.info(
            "receive_agent_text audio bytes=%d wav_duration_seconds=%s sample_rate=%s channels=%s bits_per_sample=%s",
            info["byte_length"],
            info["duration_seconds"],
            info["sample_rate"],
            info["channels"],
            info["bits_per_sample"],
        )
        if not self.stt_provider:
            raise RuntimeError(
                f"{transport.__class__.__name__} returned audio but no STT provider is configured."
            )
        stt_started = time.perf_counter()
        self._turn_boundaries["stt_start_s"] = stt_started
        with diagnostics.stage("stt", "local_stt"):
            transcript = self.stt_provider.transcribe(audio)
        self._last_stt_ms = (time.perf_counter() - stt_started) * 1000
        self._turn_boundaries["stt_end_s"] = time.perf_counter()
        diagnostics.emit("stt.latency", "local_stt", None, duration_ms=self._last_stt_ms)
        text = str(getattr(transcript, "text", transcript) or "")
        diagnostics.emit("stt.result", "local_stt", {"text": text})
        return text.strip()


def _audio_info(audio_bytes: bytes) -> dict[str, Any]:
    info: dict[str, Any] = {
        "byte_length": len(audio_bytes or b""),
        "duration_seconds": None,
        "sample_rate": None,
        "channels": None,
        "bits_per_sample": None,
    }
    if not audio_bytes:
        return info
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
            sample_rate = wav.getframerate()
            frames = wav.getnframes()
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            info.update(
                {
                    "duration_seconds": frames / sample_rate if sample_rate else None,
                    "sample_rate": sample_rate,
                    "channels": channels,
                    "bits_per_sample": sample_width * 8,
                }
            )
    except (wave.Error, EOFError):
        logger.info("receive_agent_text audio is not a readable WAV container")
    return info
