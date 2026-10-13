"""
Ties simulator + chatbot_client + evaluator together into one test run.

This is channel-agnostic on purpose: today it drives ChatbotClient, but the
same flow (generate user turn -> send to agent -> record -> repeat -> evaluate)
is exactly what a VoiceClient (Twilio-backed) would plug into later.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from app.adapters.factory import AdapterFactory
from app.config import settings
from app.evaluator import evaluate_transcript
from app.evaluation_service import _balanced_overall_score, _rag_evidence_by_turn, _resolve_rag_status
from app.schemas import MetricResult, TestRunResult, TestScenario
from app.simulator import generate_next_user_turn
from app.storage import save_run

END_TOKEN = "[END_CONVERSATION]"

def _normalize_score(metric: MetricResult) -> float:
    return metric.score

def run_scenario(scenario: TestScenario, agent_override: dict | None = None) -> TestRunResult:
    start_total = time.perf_counter()
    
    agent_config_dict = agent_override if agent_override else scenario.agent.model_dump()
    
    adapter = AdapterFactory.create(agent_config_dict)
    adapter.connect()

    try:
        for turn_index in range(scenario.max_turns):
            turn_start = time.perf_counter()
            try:
                transcript = adapter.get_transcript()
                # generate_next_user_turn currently expects the transcript in its old format or similar
                # We will adapt simulator separately if needed, but for now we pass the normalized transcript
                user_turn = generate_next_user_turn(scenario.persona, transcript)
                user_message = user_turn["message"]
                user_attachments = user_turn.get("attachments")

                if END_TOKEN in user_message or not user_message:
                    break

                adapter.send_message(user_message, agent_prompt=scenario.agent_prompt, attachments=user_attachments)
                
                elapsed = time.perf_counter() - turn_start
                logger.info(f"[STAGE: Conversation Turn] turn_index={turn_index} elapsed={elapsed:.3f}s")
            except Exception as e:
                elapsed = time.perf_counter() - turn_start
                logger.error(f"[STAGE: Conversation Turn FAILED] turn_index={turn_index} elapsed={elapsed:.3f}s exception={type(e).__name__}: {e}")
                raise
    finally:
        adapter.close()
    
    conversation = adapter.get_conversation()
    transcript = conversation.messages



    rag_evidence_by_turn = _rag_evidence_by_turn(transcript)
    rag_evaluation = _resolve_rag_status(rag_evidence_by_turn, scenario.rag_context)

    metrics: list[MetricResult] = evaluate_transcript(
        persona=scenario.persona,
        transcript=transcript,
        rag_context=None if rag_evidence_by_turn else scenario.rag_context,
        rag_evidence_by_turn=rag_evidence_by_turn or None,
    )
    rag_metrics = [
        metric for metric in metrics
        if metric.category == "rag" or metric.evidence_source in {"agent_retrieval", "reference_context"}
    ]
    if rag_metrics and rag_evaluation.status == "evaluated":
        rag_evaluation.rag_score = round(sum(metric.score for metric in rag_metrics) / len(rag_metrics), 3)
    logger.info("[SCORE DEBUG] metric_count=%d", len(metrics))
    for m in metrics:
        logger.info(
            "[SCORE DEBUG] name=%s score=%r passed=%r",
            m.name,
            m.score,
            m.passed,
        )

    logger.info(
        "[SCORE DEBUG] total=%r average=%r",
        sum(m.score for m in metrics),
        sum(m.score for m in metrics) / len(metrics) if metrics else 0.0,
    )

    overall_score = _balanced_overall_score(metrics)
    passed = overall_score >= scenario.pass_threshold

    result = TestRunResult(
        run_id=str(uuid.uuid4()),
        scenario_id=scenario.scenario_id,
        agent=scenario.agent,
        transcript=transcript,
        metrics=metrics,
        rag_evaluation=rag_evaluation,
        overall_score=overall_score,
        passed=passed,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    save_run(result)
    
    total_elapsed = time.perf_counter() - start_total
    logger.info(f"[STAGE: Total run_scenario] elapsed={total_elapsed:.3f}s")
    return result
