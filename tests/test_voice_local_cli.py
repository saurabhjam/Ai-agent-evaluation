"""
Tests for the local interactive CLI script.
"""

import sys
import yaml
import pytest
from unittest.mock import MagicMock, patch

# Provide a fake scenario
TEST_SCENARIO = {
    "scenario_id": "test_local_cli",
    "agent": {
        "channel": "voice",
        "adapter": "local",
        "config": {
            "agent_url": "http://localhost:8000/api/chat",
            "audio_dir": "artifacts/voice_test"
        }
    },
    "persona": {
        "name": "Test",
        "goal": "Test goal long enough",
        "tone": "neutral"
    },
    "max_turns": 2,
    "pass_threshold": 0.5
}


@pytest.fixture
def mock_dependencies():
    from app.schemas import MetricResult
    with patch("run_voice_local.LocalVoiceAdapter") as MockAdapter, \
         patch("run_voice_local.VoiceRecorder") as MockRecorder, \
         patch("run_voice_local.voice_to_normalized_conversation") as mock_convert, \
         patch("run_voice_local.evaluate_transcript") as mock_eval, \
         patch("builtins.input", return_value=""):
        
        # Setup adapter mock
        adapter_instance = MockAdapter.return_value
        adapter_instance.start_session.return_value = "test-session"
        adapter_instance.receive_audio.return_value = b"fake_wav"
        adapter_instance.get_transcript.return_value = []
        
        # Setup eval mock
        mock_convert.return_value.run_id = "test-run"
        mock_convert.return_value.messages = []
        
        mock_metric = MetricResult(name="Test Metric", score=1.0, passed=True, reason="")
        mock_eval.return_value = [mock_metric]
        
        yield {
            "adapter": adapter_instance,
            "recorder": MockRecorder.return_value,
            "eval": mock_eval
        }


def test_run_voice_local_flow(mock_dependencies, tmp_path):
    import run_voice_local
    
    # Write scenario file
    scenario_path = tmp_path / "scenario.yaml"
    with open(scenario_path, "w") as f:
        yaml.dump(TEST_SCENARIO, f)
        
    # Execute main
    run_voice_local.main(str(scenario_path))
    
    # Verify adapter was used correctly for 2 turns
    adapter = mock_dependencies["adapter"]
    assert adapter.start_session.call_count == 1
    assert adapter.send_audio.call_count == 2
    assert adapter.receive_audio.call_count == 2
    assert adapter.end_session.call_count == 1
    
    # Verify recorder was used correctly for 2 turns
    recorder = mock_dependencies["recorder"]
    assert recorder.record_audio.call_count == 2
    assert recorder.play_audio.call_count == 2


def test_run_voice_local_missing_url(tmp_path):
    import run_voice_local
    
    bad_scenario = {"agent": {"config": {}}}
    scenario_path = tmp_path / "bad.yaml"
    with open(scenario_path, "w") as f:
        yaml.dump(bad_scenario, f)
        
    with pytest.raises(SystemExit):
        run_voice_local.main(str(scenario_path))
