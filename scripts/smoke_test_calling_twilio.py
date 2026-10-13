"""Manual Twilio smoke test for AI Calling Agent Evaluation.

This script places a real outbound Twilio call when credentials are provided.
It does not start FastAPI, modify UI, write a database, or run background jobs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.calling.manual_config import load_manual_calling_config_from_env
from app.calling.manual_runner import ManualCallingRunner


def main() -> int:
    config = load_manual_calling_config_from_env()
    result = ManualCallingRunner().run(config)

    print("AI Calling Agent Twilio Smoke Test")
    print("=" * 40)
    print(f"Call SID: {result.call_session.provider_call_id}")
    print(f"Duration: {result.duration_seconds:.3f}s")
    print(f"Status: {result.call_session.status.value}")
    print(f"Recording SID: {result.recording.provider_recording_id if result.recording else 'NONE'}")
    print()
    print("Conversation")
    print("-" * 40)
    for message in result.calling_result.normalized_conversation.messages:
        print(f"{message.role}: {message.content}")
    if not result.calling_result.normalized_conversation.messages:
        print("No transcript supplied. Set CALLING_TRANSCRIPT_JSON to evaluate conversation content.")
    print()
    print("Evaluation Result")
    print("-" * 40)
    print(f"success: {result.evaluation_result.success}")
    print(f"passed: {result.evaluation_result.passed}")
    print(f"overall_score: {result.evaluation_result.overall_score}")
    if result.evaluation_result.error:
        print(f"error: {result.evaluation_result.error}")
    for metric in result.evaluation_result.metrics:
        print(f"- {metric.name}: score={metric.score} passed={metric.passed} reason={metric.reason}")
    print()
    print("Artifacts")
    print("-" * 40)
    for artifact in result.calling_result.artifacts:
        print(f"- {artifact.name}: path={artifact.path or 'NONE'} remote_url={artifact.remote_url or 'NONE'}")
    return 0 if result.evaluation_result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
