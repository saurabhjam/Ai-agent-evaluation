"""
Voice Runner for executing scripted voice scenarios.

Loads a voice scenario, drives a VoiceAdapter through the turns,
normalizes the conversation, and calls the existing evaluator.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from app.adapters.voice.fake import FakeVoiceAdapter
from app.voice.converter import voice_to_normalized_conversation
from app.evaluator import evaluate_transcript
from app.schemas import Persona, TestRunResult
from app.voice.metrics import run_voice_metrics
from app.voice.config import VoiceMetricsConfig

logger = logging.getLogger(__name__)


def run_voice_scenario(scenario_data: dict) -> TestRunResult:
    """
    Executes a voice scenario end-to-end.

    Args:
        scenario_data: The loaded YAML dictionary for the voice scenario.
    """
    scenario_id = scenario_data.get("scenario_id", scenario_data.get("scenario", {}).get("name", "unknown_scenario"))
    persona_data = scenario_data.get("persona", {})
    persona = Persona(
        name=persona_data.get("name", "Unknown"),
        goal=persona_data.get("goal", ""),
        tone=persona_data.get("tone", ""),
        edge_case=persona_data.get("edge_case", "")
    )
    
    rag_context = scenario_data.get("rag_context", None)
    rag_config = scenario_data.get("rag_config") or scenario_data.get("voice", {}).get("rag_config")
    
    # Extract turns from the scenario
    turns = scenario_data.get("conversation", {}).get("turns", [])
    
    # We extract all agent texts to seed the FakeVoiceAdapter
    agent_responses = [t["text"] for t in turns if t["speaker"] == "agent"]
    
    adapter_config = {
        "responses": agent_responses,
        "latency_ms": 150.0,
    }
    
    adapter = FakeVoiceAdapter(config=adapter_config)
    adapter.start_session()
    
    turn_index = 0
    try:
        # We iterate over the turns, simulating the flow
        # In a real system, the user speaks, and the adapter automatically replies via STT/LLM/TTS.
        # Here, we drive it step by step.
        for t in turns:
            speaker = t["speaker"]
            text = t["text"]
            
            if speaker == "user":
                adapter.send_text(text, turn_index=turn_index)
            elif speaker == "agent":
                # The fake adapter picks from the responses list we provided
                reply = adapter.receive_text()
                if reply != text:
                    logger.warning(f"Expected agent to reply with '{text}', but got '{reply}'")
                turn_index += 1
                
    finally:
        vc = adapter.end_session()
        
    normalized = voice_to_normalized_conversation(vc, rag_config=rag_config)
    rag_evidence_by_turn = _rag_evidence_by_turn(normalized.messages)
    
    metrics = evaluate_transcript(
        persona=persona,
        transcript=normalized.messages,
        rag_context=None if rag_evidence_by_turn else rag_context,
        rag_evidence_by_turn=rag_evidence_by_turn or None,
    )
    
    overall_score = round(sum(m.score for m in metrics) / len(metrics), 3) if metrics else 0.0
    pass_threshold = scenario_data.get("pass_threshold", 0.7)
    passed = overall_score >= pass_threshold
    
    agent_data = scenario_data.get("agent", {})
    if "channel" not in agent_data:
        agent_data["channel"] = scenario_data.get("channel", "voice")
        
    voice_metrics_config_data = scenario_data.get("voice", {}).get("metrics", {})
    voice_metrics_config = VoiceMetricsConfig(**voice_metrics_config_data)
    voice_metrics = run_voice_metrics(vc, voice_metrics_config)
        
    return TestRunResult(
        run_id=normalized.run_id,
        scenario_id=scenario_id,
        agent=agent_data,
        transcript=normalized.messages,
        metrics=metrics,
        voice_metrics=voice_metrics,
        overall_score=overall_score,
        passed=passed,
        created_at=datetime.now(timezone.utc).isoformat()
    )


def _rag_evidence_by_turn(messages: list) -> list[dict]:
    evidence_by_turn: list[dict] = []
    for message in messages:
        if getattr(message, "role", None) != "agent":
            continue
        rag = getattr(message, "rag_evidence", None)
        if rag is None or not getattr(rag, "available", False):
            continue
        contexts = [ctx for ctx in (getattr(rag, "contexts", None) or []) if isinstance(ctx, str) and ctx.strip()]
        if not contexts:
            continue
        evidence_by_turn.append(
            {
                "actual_output": getattr(message, "content", ""),
                "contexts": contexts,
                "citations": getattr(rag, "citations", None),
                "metadata": getattr(rag, "metadata", None),
                "source": getattr(rag, "source", "agent_retrieval"),
            }
        )
    return evidence_by_turn
