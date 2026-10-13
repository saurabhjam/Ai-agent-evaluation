"""
Voice-specific deterministic evaluation metrics.

These metrics run on the VoiceConversation object before it is converted
into a NormalizedConversation, and they do not use the LLM evaluator.
"""

from __future__ import annotations

import os
from datetime import datetime

from app.schemas import MetricResult
from app.models.voice import VoiceConversation, Speaker, SessionStatus, VoiceEventType
from app.voice.config import VoiceMetricsConfig


def evaluate_latency(vc: VoiceConversation, config: VoiceMetricsConfig) -> MetricResult:
    if not config.latency.enabled:
        return MetricResult(name="Response Latency", score=1.0, reason="Skipped", passed=True)

    agent_turns = [t for t in vc.turns if t.speaker == Speaker.agent]
    if not agent_turns:
        return MetricResult(name="Response Latency", score=0.0, reason="NOT_AVAILABLE (No agent turns)", passed=False)

    latencies = [t.latency_ms for t in agent_turns if t.latency_ms is not None]
    if not latencies:
        return MetricResult(name="Response Latency", score=0.0, reason="NOT_AVAILABLE (No timestamp data)", passed=False)

    avg_latency = sum(latencies) / len(latencies)
    max_latency = max(latencies)
    
    passed = True
    reason = "All measured response latencies were within the configured threshold."
    if max_latency > config.latency.failure_ms:
        passed = False
        reason = f"Maximum latency ({max_latency:.0f} ms) exceeded failure threshold ({config.latency.failure_ms} ms)."
    elif avg_latency > config.latency.warning_ms:
        passed = False
        reason = f"Average latency ({avg_latency:.0f} ms) exceeded warning threshold ({config.latency.warning_ms} ms)."

    score = 1.0 if passed else 0.0
    return MetricResult(name="Response Latency", score=score, reason=reason, passed=passed)


def evaluate_turn_taking(vc: VoiceConversation, config: VoiceMetricsConfig) -> MetricResult:
    if not config.turn_taking.enabled:
        return MetricResult(name="Turn Taking", score=1.0, reason="Skipped", passed=True)

    if not vc.turns:
        return MetricResult(name="Turn Taking", score=1.0, reason="No turns.", passed=True)

    # Valid sequences usually alternate. But sometimes multiple user/agent turns happen in a row.
    # We will flag strictly invalid sequences. A basic check is just ensuring we didn't have 
    # weird empty turns or 3 agent turns back-to-back without user interaction, etc.
    # For now, we'll check if the agent spoke completely without the user ever speaking.
    
    # Actually, a strict check for consecutive identical speakers without interruption is good.
    consecutive_agent = 0
    consecutive_user = 0
    passed = True
    reason = "User and agent turns followed the expected turn sequence."
    
    for turn in vc.turns:
        if turn.speaker == Speaker.agent:
            consecutive_agent += 1
            consecutive_user = 0
        elif turn.speaker == Speaker.user:
            consecutive_user += 1
            consecutive_agent = 0
            
        if consecutive_agent > 2:
            passed = False
            reason = "Invalid sequence: Agent took too many consecutive turns."
            break
        if consecutive_user > 3:
            # Users can speak multiple times if STT fragments it.
            pass

    score = 1.0 if passed else 0.0
    return MetricResult(name="Turn Taking", score=score, reason=reason, passed=passed)


def evaluate_interruption(vc: VoiceConversation, config: VoiceMetricsConfig) -> MetricResult:
    if not config.interruption.enabled:
        return MetricResult(name="Interruptions", score=1.0, reason="Skipped", passed=True)

    interruptions = len(vc.interruptions())
    
    passed = interruptions <= config.interruption.max_allowed
    reason = "No interruptions were detected." if interruptions == 0 else f"{interruptions} interruptions detected, which is within the allowed limit."
    if not passed:
        reason = f"Too many interruptions ({interruptions} > {config.interruption.max_allowed})."
        
    score = 1.0 if passed else 0.0
    return MetricResult(name="Interruptions", score=score, reason=reason, passed=passed)


def evaluate_silence(vc: VoiceConversation, config: VoiceMetricsConfig) -> MetricResult:
    if not config.silence.enabled:
        return MetricResult(name="Silence", score=1.0, reason="Skipped", passed=True)

    events_with_time = [e for e in vc.events if e.timestamp]
    if len(events_with_time) < 2:
        return MetricResult(name="Silence", score=0.0, reason="NOT_AVAILABLE (Insufficient timestamp events)", passed=False)

    max_gap_ms = 0.0
    # Calculate gaps between consecutive events
    for i in range(1, len(events_with_time)):
        ts1 = events_with_time[i-1].timestamp.replace("Z", "+00:00")
        ts2 = events_with_time[i].timestamp.replace("Z", "+00:00")
        t1 = datetime.fromisoformat(ts1)
        t2 = datetime.fromisoformat(ts2)
        gap_ms = (t2 - t1).total_seconds() * 1000.0
        if gap_ms > max_gap_ms:
            max_gap_ms = gap_ms
            
    passed = max_gap_ms <= config.silence.max_gap_ms
    reason = "All recorded gaps were within the configured silence threshold."
    if not passed:
        reason = f"A recorded gap ({max_gap_ms:.0f} ms) exceeded the configured silence threshold ({config.silence.max_gap_ms} ms)."
        
    score = 1.0 if passed else 0.0
    return MetricResult(name="Silence", score=score, reason=reason, passed=passed)


def evaluate_audio_evidence(vc: VoiceConversation, config: VoiceMetricsConfig) -> MetricResult:
    if not config.audio.enabled:
        return MetricResult(name="Audio Evidence", score=1.0, reason="Skipped", passed=True)

    total_expected = len(vc.turns)
    valid_artifacts = 0
    
    for turn in vc.turns:
        if turn.audio_path and os.path.exists(turn.audio_path):
            valid_artifacts += 1
            
    passed = valid_artifacts == total_expected and total_expected > 0
    reason = "All expected audio artifacts were present and valid."
    
    if total_expected == 0:
        passed = False
        reason = "No turns to validate."
    elif not passed:
        reason = f"Only {valid_artifacts}/{total_expected} expected audio artifacts were found or valid."
        
    score = 1.0 if passed else 0.0
    return MetricResult(name="Audio Evidence", score=score, reason=reason, passed=passed)


def evaluate_session_completion(vc: VoiceConversation, config: VoiceMetricsConfig) -> MetricResult:
    if not config.session_completion.enabled:
        return MetricResult(name="Session Completion", score=1.0, reason="Skipped", passed=True)

    passed = True
    reason = "The voice session completed successfully."
    
    if not vc.session.started_at:
        passed = False
        reason = "Session missing started_at timestamp."
    elif not vc.session.ended_at:
        passed = False
        reason = "Session missing ended_at timestamp."
    elif vc.session.status != SessionStatus.completed:
        passed = False
        reason = f"Session status is {vc.session.status.value}, expected 'completed'."
        
    score = 1.0 if passed else 0.0
    return MetricResult(name="Session Completion", score=score, reason=reason, passed=passed)


def run_voice_metrics(vc: VoiceConversation, config: VoiceMetricsConfig) -> list[MetricResult]:
    """Runs all enabled deterministic voice metrics."""
    return [
        evaluate_latency(vc, config),
        evaluate_turn_taking(vc, config),
        evaluate_interruption(vc, config),
        evaluate_silence(vc, config),
        evaluate_audio_evidence(vc, config),
        evaluate_session_completion(vc, config),
    ]
