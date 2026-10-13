"""
CLI for running a fully automated LiveKit voice test.
"""

import argparse
import sys
import yaml
import time
from pathlib import Path

from app.adapters.voice.livekit import LiveKitVoiceAdapter
from app.voice.persona import VoicePersonaEngine
from app.voice.converter import voice_to_normalized_conversation
from app.voice.metrics import run_voice_metrics
from app.voice.config import VoiceMetricsConfig
from app.evaluator import evaluate_transcript
from app.schemas import TestRunResult, Persona
from app.voice.recorder import VoiceRecorder


def main(scenario_path: str):
    with open(scenario_path) as f:
        scenario_data = yaml.safe_load(f)

    # 1. Configuration
    voice_config = scenario_data.get("voice", {})
    adapter_name = voice_config.get("adapter")
    
    if adapter_name != "livekit":
        print("ERROR: Scenario does not specify adapter: 'livekit'")
        sys.exit(1)
        
    adapter_config = voice_config.get("config", {})

    max_turns = scenario_data.get("max_turns", 10)
    max_session_duration_seconds = scenario_data.get("max_session_duration_seconds", 900)
    persona = Persona(**scenario_data["persona"])

    # 2. Setup
    from dotenv import load_dotenv
    from app.config import PROJECT_ROOT
    load_dotenv(PROJECT_ROOT / ".env")

    print("Initializing LiveKitVoiceAdapter (this will check environment variables)...")
    try:
        adapter = LiveKitVoiceAdapter(config=adapter_config)
    except Exception as exc:
        print(f"Failed to initialize adapter: {exc}")
        sys.exit(1)

    # Re-use TTS from adapter
    tts = adapter._tts
    
    engine = VoicePersonaEngine(
        persona=persona,
        adapter=adapter,
        tts_provider=tts,
        max_turns=max_turns,
        max_session_duration_seconds=max_session_duration_seconds
    )

    print("\n========================================")
    print("LIVEKIT VOICE EVALUATION")
    print("========================================")
    print(f"Scenario: {scenario_path}")
    print(f"Channel: voice")
    print(f"Adapter: livekit")
    print(f"Agent: {adapter_config.get('agent_name', 'my-agent')}")
    print("========================================")
    
    try:
        vc = engine.run_automated_session()
    except TimeoutError as e:
        print(f"Error: {e}")
        sys.exit(1)
        
    print(f"\nSession ID: {vc.session.session_id}\n")
    
    # 3. Print Transcript
    user_audio_count = 0
    agent_audio_count = 0
    
    turn_number = 1
    for turn in vc.turns:
        speaker_val = turn.speaker.value if hasattr(turn.speaker, "value") else str(turn.speaker)
        if speaker_val == "user":
            user_audio_count += 1
            print(f"--- Turn {turn_number} ---")
            print(f"Persona: {turn.text}")
        elif speaker_val == "agent":
            agent_audio_count += 1
            print(f"Agent: {turn.text}\n")
            turn_number += 1

    # 4. Generate Audio Evidence
    session_dir = Path(adapter._session_dir) if adapter._session_dir else Path(adapter_config.get("audio_dir", "artifacts/voice")) / vc.session.session_id
    scenario_id = scenario_data.get("scenario_id", "automated_voice_test")
    
    conv_data = engine.generate_full_audio_and_json(vc, session_dir, scenario_id)
    
    print("\n========================================")
    print("AUDIO EVIDENCE")
    print("========================================")
    print(f"User audio files: {user_audio_count}")
    print(f"Agent audio files: {agent_audio_count}\n")
    print("Full conversation:")
    print(f"{conv_data.get('full_audio_path')}")
    
    print("\n========================================")
    print("VOICE EVALUATION")
    print("========================================")

    # 5. Evaluation
    normalized = voice_to_normalized_conversation(vc, scenario_id=scenario_id)
    
    voice_metrics_config_data = voice_config.get("metrics", {})
    voice_metrics_config = VoiceMetricsConfig(**voice_metrics_config_data)
    voice_metrics = run_voice_metrics(vc, voice_metrics_config)
    
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
        agent={"channel": "voice", "adapter": "livekit", "config": adapter_config},
        transcript=normalized.messages,
        metrics=metrics,
        voice_metrics=voice_metrics,
        overall_score=overall_score,
        passed=passed,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )

    for m in result.metrics:
        status = "PASS" if m.passed else "FAIL"
        print(f"{m.name[:26]:26}: {m.score:.2f} {status}")
        print(f"Reason: {m.reason}\n")
        
    if result.voice_metrics:
        print("VOICE METRICS:")
        for m in result.voice_metrics:
            status = "PASS" if m.passed else "FAIL"
            print(f"{m.name[:26]:26}: {status}")
            print(f"Reason: {m.reason}\n")

    print(f"\nOverall:         {result.overall_score:.2f} {'PASS' if result.passed else 'FAIL'}\n")

    print("========================================")
    print("CONVERSATION AUDIO")
    print("========================================")
    print("Full conversation:")
    print(f"{conv_data.get('full_audio_path')}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an automated LiveKit voice scenario")
    parser.add_argument("scenario", help="Path to scenario.yaml")
    args = parser.parse_args()
    
    main(args.scenario)
