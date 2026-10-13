"""
End-to-End Tests for the Voice Evaluation flow.

Verifies that a voice scenario runs through the runner, the adapter,
the conversation model, and the existing evaluator correctly.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from app.schemas import TestRunResult
from app.voice.runner import run_voice_scenario


def test_voice_scenario_e2e_execution(tmp_path):
    """
    Test that a basic voice scenario executes end-to-end.
    Since we don't want to actually call the LLM during basic tests,
    we patch the evaluator to return dummy metrics.
    """
    scenario_data = {
        "scenario_id": "test_voice_e2e",
        "channel": "voice",
        "agent": {"adapter": "fake"},
        "persona": {
            "name": "TestUser",
            "goal": "Test goal with at least ten characters",
            "tone": "neutral"
        },
        "pass_threshold": 0.5,
        "conversation": {
            "turns": [
                {"speaker": "user", "text": "Hello agent."},
                {"speaker": "agent", "text": "Hello user, how can I help?"},
                {"speaker": "user", "text": "That is all."},
                {"speaker": "agent", "text": "Goodbye."}
            ]
        }
    }

    # Patch the evaluator so we don't need a real LLM API key
    with patch("app.voice.runner.evaluate_transcript") as mock_eval:
        from app.schemas import MetricResult
        mock_eval.return_value = [
            MetricResult(name="Goal Completion", score=1.0, reason="ok", passed=True),
            MetricResult(name="Persona and Tone Adherence", score=1.0, reason="ok", passed=True),
            MetricResult(name="Conversational Quality", score=1.0, reason="ok", passed=True),
        ]
        
        result = run_voice_scenario(scenario_data)
        
        assert isinstance(result, TestRunResult)
        assert result.scenario_id == "test_voice_e2e"
        assert result.passed is True
        assert result.overall_score == 1.0
        assert len(result.metrics) == 3
        assert result.agent.channel == "voice"
        
        # Check transcript
        assert len(result.transcript) == 4
        assert result.transcript[0].role == "simulated_user"
        assert result.transcript[0].content == "Hello agent."
        assert result.transcript[1].role == "agent"
        assert result.transcript[1].content == "Hello user, how can I help?"
        
        # Metadata should contain voice-specific things
        assert "audio_path" in result.transcript[0].metadata
        assert "audio_path" in result.transcript[1].metadata
        
        # Session ID must be propagated properly
        assert "session_id" in result.transcript[0].metadata
        assert len(result.transcript[0].metadata["session_id"]) > 0
        
        # Verify the audio files actually exist
        audio_path_0 = result.transcript[0].metadata["audio_path"]
        assert os.path.exists(audio_path_0)
