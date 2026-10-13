"""
Tests for deterministic voice-specific evaluation metrics.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from app.models.voice import (
    VoiceConversation, VoiceSession, VoiceTurn, VoiceEvent, VoiceEventType,
    Speaker, SessionStatus
)
from app.voice.config import VoiceMetricsConfig
from app.voice.metrics import (
    evaluate_latency, evaluate_turn_taking, evaluate_interruption,
    evaluate_silence, evaluate_audio_evidence, evaluate_session_completion
)


def _create_mock_conversation(turns=None, events=None, status=SessionStatus.completed) -> VoiceConversation:
    session = VoiceSession(
        session_id="test_session",
        call_id="test_call",
        channel="voice",
        started_at="2023-01-01T12:00:00Z",
        ended_at="2023-01-01T12:05:00Z",
        status=status,
    )
    return VoiceConversation(
        session=session,
        turns=turns or [],
        events=events or []
    )


def test_evaluate_latency_pass():
    config = VoiceMetricsConfig()
    turns = [
        VoiceTurn(speaker=Speaker.user, text="hello"),
        VoiceTurn(speaker=Speaker.agent, text="hi", latency_ms=500.0),
        VoiceTurn(speaker=Speaker.agent, text="there", latency_ms=600.0),
    ]
    vc = _create_mock_conversation(turns=turns)
    result = evaluate_latency(vc, config)
    assert result.passed is True
    assert "within the configured threshold" in result.reason


def test_evaluate_latency_fail_max():
    config = VoiceMetricsConfig()
    config.latency.failure_ms = 1000.0
    turns = [
        VoiceTurn(speaker=Speaker.user, text="hello"),
        VoiceTurn(speaker=Speaker.agent, text="hi", latency_ms=1500.0),
    ]
    vc = _create_mock_conversation(turns=turns)
    result = evaluate_latency(vc, config)
    assert result.passed is False
    assert "exceeded failure threshold" in result.reason


def test_evaluate_latency_missing_data():
    config = VoiceMetricsConfig()
    # Agent turn but no latency
    turns = [VoiceTurn(speaker=Speaker.agent, text="hi")]
    vc = _create_mock_conversation(turns=turns)
    result = evaluate_latency(vc, config)
    assert result.passed is False
    assert "NOT_AVAILABLE" in result.reason


def test_evaluate_turn_taking_pass():
    config = VoiceMetricsConfig()
    turns = [
        VoiceTurn(speaker=Speaker.user, text="a"),
        VoiceTurn(speaker=Speaker.agent, text="b"),
        VoiceTurn(speaker=Speaker.user, text="c"),
        VoiceTurn(speaker=Speaker.agent, text="d"),
    ]
    vc = _create_mock_conversation(turns=turns)
    result = evaluate_turn_taking(vc, config)
    assert result.passed is True


def test_evaluate_turn_taking_fail():
    config = VoiceMetricsConfig()
    # 3 consecutive agent turns is considered fail by our current logic
    turns = [
        VoiceTurn(speaker=Speaker.agent, text="a"),
        VoiceTurn(speaker=Speaker.agent, text="b"),
        VoiceTurn(speaker=Speaker.agent, text="c"),
    ]
    vc = _create_mock_conversation(turns=turns)
    result = evaluate_turn_taking(vc, config)
    assert result.passed is False
    assert "Invalid sequence" in result.reason


def test_evaluate_interruption_pass():
    config = VoiceMetricsConfig()
    config.interruption.max_allowed = 1
    turns = [
        VoiceTurn(speaker=Speaker.user, text="hello", interrupted=True),
    ]
    vc = _create_mock_conversation(turns=turns)
    result = evaluate_interruption(vc, config)
    assert result.passed is True


def test_evaluate_interruption_fail():
    config = VoiceMetricsConfig()
    config.interruption.max_allowed = 0
    turns = [
        VoiceTurn(speaker=Speaker.user, text="stop", interrupted=True),
    ]
    vc = _create_mock_conversation(turns=turns)
    result = evaluate_interruption(vc, config)
    assert result.passed is False


def test_evaluate_silence_pass():
    config = VoiceMetricsConfig()
    config.silence.max_gap_ms = 5000.0
    events = [
        VoiceEvent(event_type=VoiceEventType.speech_started, timestamp="2023-01-01T12:00:00.000Z"),
        VoiceEvent(event_type=VoiceEventType.speech_ended, timestamp="2023-01-01T12:00:01.000Z"),
    ]
    vc = _create_mock_conversation(events=events)
    result = evaluate_silence(vc, config)
    assert result.passed is True
    assert "within the configured silence threshold" in result.reason


def test_evaluate_silence_fail():
    config = VoiceMetricsConfig()
    config.silence.max_gap_ms = 500.0
    events = [
        VoiceEvent(event_type=VoiceEventType.speech_started, timestamp="2023-01-01T12:00:00.000Z"),
        VoiceEvent(event_type=VoiceEventType.speech_ended, timestamp="2023-01-01T12:00:01.000Z"),
    ]
    vc = _create_mock_conversation(events=events)
    result = evaluate_silence(vc, config)
    assert result.passed is False
    assert "exceeded the configured silence threshold" in result.reason


def test_evaluate_silence_missing_timestamps():
    config = VoiceMetricsConfig()
    events = [
        VoiceEvent(event_type=VoiceEventType.speech_started, timestamp=""),
        VoiceEvent(event_type=VoiceEventType.speech_ended, timestamp=""),
    ]
    vc = _create_mock_conversation(events=events)
    result = evaluate_silence(vc, config)
    assert result.passed is False
    assert "NOT_AVAILABLE" in result.reason


def test_evaluate_audio_evidence_missing():
    config = VoiceMetricsConfig()
    turns = [VoiceTurn(speaker=Speaker.user, text="hello")]
    vc = _create_mock_conversation(turns=turns)
    result = evaluate_audio_evidence(vc, config)
    assert result.passed is False


def test_evaluate_audio_evidence_pass(tmp_path):
    config = VoiceMetricsConfig()
    p = tmp_path / "test.wav"
    p.write_text("fake audio data")
    
    turns = [VoiceTurn(speaker=Speaker.user, text="hello", audio_path=str(p))]
    vc = _create_mock_conversation(turns=turns)
    result = evaluate_audio_evidence(vc, config)
    assert result.passed is True


def test_evaluate_session_completion_pass():
    config = VoiceMetricsConfig()
    vc = _create_mock_conversation(status=SessionStatus.completed)
    result = evaluate_session_completion(vc, config)
    assert result.passed is True


def test_evaluate_session_completion_fail():
    config = VoiceMetricsConfig()
    vc = _create_mock_conversation(status=SessionStatus.failed)
    result = evaluate_session_completion(vc, config)
    assert result.passed is False
