"""
CLI for running a fully automated persona voice test.
"""

import argparse
import sys
import yaml
import time
from pathlib import Path

from app.adapters.voice.local import LocalVoiceAdapter
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
    agent_config = scenario_data.get("agent", {})
    adapter_config = agent_config.get("config", {})
    if not adapter_config.get("agent_url"):
        print("ERROR: No 'agent_url' found in scenario agent.config.")
        sys.exit(1)

    max_turns = scenario_data.get("max_turns", 10)
    max_session_duration_seconds = scenario_data.get("max_session_duration_seconds", 300)
    persona = Persona(**scenario_data["persona"])

    # 2. Setup
    adapter = LocalVoiceAdapter(config=adapter_config)
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
    print("AUTOMATED VOICE PERSONA TEST")
    print("========================================")
    
    vc = engine.run_automated_session()
    
    print(f"\nSession: {vc.session.session_id}\n")
    
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
    
    voice_metrics_config_data = scenario_data.get("voice", {}).get("metrics", {})
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
        agent={"channel": "voice", "adapter": "local", "config": adapter_config},
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
    
    if conv_data.get("full_audio_path"):
        while True:
            choice = input("[P] Play full conversation\n[Enter] Exit\n> ").strip().lower()
            if choice == "p":
                try:
                    recorder = VoiceRecorder()
                    audio_bytes = Path(conv_data["full_audio_path"]).read_bytes()
                    print("[Playing audio...]")
                    recorder.play_audio(audio_bytes)
                except Exception as e:
                    print(f"Playback failed: {e}")
            else:
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an automated persona voice scenario")
    parser.add_argument("scenario", help="Path to scenario.yaml")
    args = parser.parse_args()
    
    main(args.scenario)
