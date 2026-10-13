"""
CLI for running a single voice scenario directly.

Usage:
    python run_voice_scenario.py scenarios/voice/refund_request.yaml
"""

import argparse
import sys
import yaml

from app.voice.runner import run_voice_scenario

def main(path: str):
    with open(path) as f:
        scenario_data = yaml.safe_load(f)

    # Run the voice scenario
    try:
        result = run_voice_scenario(scenario_data)
    except Exception as e:
        print(f"Error running voice scenario: {e}")
        sys.exit(1)

    print("\n========================================")
    print("VOICE EVALUATION")
    print("========================================")
    print(f"\nScenario: {result.scenario_id}")
    print(f"Channel: {result.agent.channel if hasattr(result.agent, 'channel') else scenario_data.get('channel', 'voice')}")
    print(f"Adapter: {result.agent.adapter if hasattr(result.agent, 'adapter') else scenario_data.get('agent', {}).get('adapter', 'fake')}")
    print(f"\nSession ID: {result.transcript[0].metadata.get('session_id', 'unknown') if result.transcript and getattr(result.transcript[0], 'metadata', None) else 'unknown'}")

    turn_count = len(result.transcript)
    # Each turn generates an audio artifact in FakeVoiceAdapter
    audio_artifacts = len([t for t in result.transcript if getattr(t, 'metadata', {}).get('audio_path')])
    
    print(f"\nTurns: {turn_count}")
    print(f"Audio artifacts: {audio_artifacts}")

    print("\n----------------------------------------")
    print("EVALUATION")
    print("----------------------------------------\n")

    for m in result.metrics:
        status = "PASS" if m.passed else "FAIL"
        print(f"{m.name:26}: {m.score:.2f} {status}")
        
    if getattr(result, "voice_metrics", None):
        print("\n----------------------------------------")
        print("VOICE METRICS")
        print("----------------------------------------\n")
        
        for m in result.voice_metrics:
            status = "PASS" if m.passed else "FAIL"
            print(f"{m.name}:")
            if m.reason and m.reason not in ("Skipped", "NOT_AVAILABLE"):
                print(f"{m.reason}")
            print(f"{status}\n")

    print(f"Overall:         {result.overall_score:.2f} {'PASS' if result.passed else 'FAIL'}\n")
    print("========================================\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a voice scenario")
    parser.add_argument("scenario", help="Path to scenario.yaml")
    args = parser.parse_args()
    
    main(args.scenario)
