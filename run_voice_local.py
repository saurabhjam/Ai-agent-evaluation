"""
CLI for running a local interactive voice session.

Allows a user to speak into their microphone and hear agent responses played
back over their speakers, while capturing the full sequence of events for
deep evaluation metrics.

Usage:
    python run_voice_local.py scenarios/voice/refund_request.yaml
"""

import argparse
import sys
import yaml
import time

from app.adapters.voice.local import LocalVoiceAdapter
from app.voice.recorder import VoiceRecorder
from app.voice.converter import voice_to_normalized_conversation
from app.voice.metrics import run_voice_metrics
from app.voice.config import VoiceMetricsConfig
from app.evaluator import evaluate_transcript
from app.schemas import TestRunResult


def main(scenario_path: str):
    with open(scenario_path) as f:
        scenario_data = yaml.safe_load(f)

    # 1. Configuration
    agent_config = scenario_data.get("agent", {})
    adapter_config = agent_config.get("config", {})
    if not adapter_config.get("agent_url"):
        print("ERROR: No 'agent_url' found in scenario agent.config. Cannot run local voice flow.")
        sys.exit(1)

    # 2. Setup
    adapter = LocalVoiceAdapter(config=adapter_config)
    recorder = VoiceRecorder(
        sample_rate=adapter_config.get("sample_rate", 16000),
        channels=1
    )
    
    # Optional parameters for interactivity
    record_duration = 5.0  # seconds (used as fallback or fixed mode)

    # 3. Interactive Loop
    print("\n========================================")
    print("LOCAL VOICE AGENT TEST")
    print("========================================")
    
    session_id = adapter.start_session()
    print(f"\nSession: {session_id}\n")

    turn_count = 0
    max_turns = scenario_data.get("max_turns", 6)

    try:
        while turn_count < max_turns:
            print(f"--- Turn {turn_count + 1}/{max_turns} ---")
            
            # Record user
            input("Press Enter to start recording (speak, then pause to stop)... or Ctrl+C to exit.")
            print("> Listening...")
            user_wav = recorder.record_audio(use_vad=True)
            
            # Send to adapter (transcribes & stores user turn)
            adapter.send_audio(user_wav, turn_index=turn_count)
            
            # Print user transcript
            transcript = adapter.get_transcript()
            if transcript and transcript[-1].speaker.value == "user":
                print(f"\nYou: {transcript[-1].text}")
                
            # Receive from agent (posts audio, synthesizes response, stores agent turn)
            print("> Agent is thinking...")
            agent_wav = adapter.receive_audio(timeout_seconds=30.0)
            
            # Print agent transcript
            transcript = adapter.get_transcript()
            if transcript and transcript[-1].speaker.value == "agent":
                print(f"Agent: {transcript[-1].text}\n")
                
            # Play agent audio
            print("[Agent audio playing...]")
            recorder.play_audio(agent_wav)
            
            turn_count += 1
            print()
            
    except KeyboardInterrupt:
        print("\n\nUser exited session.")
    except Exception as e:
        print(f"\n\nError during session: {e}")
    finally:
        vc = adapter.end_session()
    
    print("\n========================================")
    print("VOICE EVALUATION")
    print("========================================")

    # 4. Evaluation
    scenario_id = scenario_data.get("scenario_id", "local_voice_test")
    normalized = voice_to_normalized_conversation(vc, scenario_id=scenario_id)
    
    # Deterministic Metrics
    voice_metrics_config_data = scenario_data.get("voice", {}).get("metrics", {})
    voice_metrics_config = VoiceMetricsConfig(**voice_metrics_config_data)
    voice_metrics = run_voice_metrics(vc, voice_metrics_config)
    
    # LLM Metrics
    from app.schemas import Persona
    persona = Persona(**scenario_data["persona"])
    rag_context = scenario_data.get("rag_context")
    metrics = evaluate_transcript(
        persona=persona,
        transcript=normalized.messages,
        rag_context=rag_context
    )
    overall_score = round(sum(m.score for m in metrics) / len(metrics), 3) if metrics else 0.0
    pass_threshold = scenario_data.get("pass_threshold", 0.7)
    passed = overall_score >= pass_threshold
    
    result = TestRunResult(
        run_id=normalized.run_id,
        scenario_id=scenario_id,
        agent={"channel": "voice", "adapter": "local", "config": adapter_config},
        transcript=normalized.messages,
        metrics=metrics,
        voice_metrics=voice_metrics,
        overall_score=overall_score,
        passed=passed,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )

    # 5. Output
    for m in result.metrics:
        status = "PASS" if m.passed else "FAIL"
        print(f"{m.name:26}: {m.score:.2f} {status}")
        
    if result.voice_metrics:
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
    parser = argparse.ArgumentParser(description="Run a real local voice scenario interactively")
    parser.add_argument("scenario", help="Path to scenario.yaml")
    args = parser.parse_args()
    
    main(args.scenario)
