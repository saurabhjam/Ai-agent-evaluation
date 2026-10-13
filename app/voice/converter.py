"""
Voice -> Chat conversion boundary.

This module provides the clean conversion layer between VoiceConversation
(voice-channel evidence) and the shared evaluation core.

The conversion flow is:

    VoiceConversation
         |
         v
    voice_to_normalized_conversation()
         |
         v
    NormalizedConversation            <- same type the chat evaluator uses
         |
         v
    evaluate_transcript()             <- existing evaluator, unchanged
         |
         v
    list[MetricResult]

Additionally, voice_to_deepeval_test_case() provides a direct conversion
to a DeepEval ConversationalTestCase for voice-specific DeepEval metrics.

IMPORTANT:
  - This file is the ONLY place that knows about both VoiceConversation
    and DeepEval types.
  - The evaluator (app/evaluator.py) is NOT modified.
  - The VoiceAdapter (app/adapters/voice/) does NOT import DeepEval.
  - All DeepEval-specific logic that may differ between versions is
    isolated here, behind this single boundary.

DeepEval version compatibility:
  Tested against deepeval==2.0.9.
  ConversationalTestCase(turns=[LLMTestCase(...)]) is the confirmed API.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.models.conversation import ConversationMessage, NormalizedConversation, RAGEvidence, ToolCallInfo
from app.models.voice import Speaker, VoiceConversation, VoiceTurn
from app.rag import extract_rag_evidence, get_values_by_path


def voice_to_normalized_conversation(
    vc: VoiceConversation,
    run_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    rag_config: Optional[dict[str, Any]] = None,
) -> NormalizedConversation:
    """
    Convert a VoiceConversation into the shared NormalizedConversation format.

    This allows the existing evaluate_transcript() evaluator to score voice
    conversations using exactly the same logic as chat conversations.

    Speaker mapping:
      VoiceTurn.speaker == Speaker.user    ->  ConversationMessage.role = "simulated_user"
      VoiceTurn.speaker == Speaker.agent   ->  ConversationMessage.role = "agent"
      VoiceTurn.speaker == Speaker.system  ->  ConversationMessage.role = "system"

    Parameters
    ----------
    vc:
        Fully populated VoiceConversation from a VoiceAdapter.
    run_id:
        Optional run ID.  If not provided, a new UUID is generated.

    Returns
    -------
    NormalizedConversation
        Ready to pass into evaluate_transcript().
    """
    _role_map = {
        Speaker.user: "simulated_user",
        Speaker.agent: "agent",
        Speaker.system: "system",
    }

    messages: list[ConversationMessage] = []
    for i, turn in enumerate(vc.turns):
        role = _role_map.get(turn.speaker, "system")
        rag_evidence = _turn_rag_evidence(turn, rag_config)
        msg = ConversationMessage(
            role=role,
            content=turn.text,
            turn_index=i,
            timestamp=turn.timestamp,
            metadata={
                "session_id": vc.session.session_id,
                "audio_path": turn.audio_path,
                "latency_ms": turn.latency_ms,
                "interrupted": turn.interrupted,
                "confidence": turn.confidence,
                **(turn.metadata or {}),
            },
            rag_evidence=rag_evidence,
        )
        messages.append(msg)

    metadata = {
        "call_id": vc.session.call_id,
        "event_count": len(vc.events),
        "interruption_count": len(vc.interruptions()),
        "average_latency_ms": vc.average_agent_latency_ms(),
        "duration_seconds": vc.duration_seconds(),
        **(vc.metadata or {}),
    }
    
    if scenario_id is not None:
        metadata["scenario_id"] = scenario_id

    return NormalizedConversation(
        run_id=run_id or str(uuid.uuid4()),
        session_id=vc.session.session_id,
        channel="voice",
        messages=messages,
        start_time=vc.session.started_at,
        end_time=vc.session.ended_at,
        status=vc.session.status.value if vc.session.status else "completed",
        metadata=metadata,
    )


def _turn_rag_evidence(turn: VoiceTurn, rag_config: Optional[dict[str, Any]]) -> Optional[RAGEvidence]:
    if turn.speaker != Speaker.agent:
        return None
    if turn.rag_evidence is not None:
        return turn.rag_evidence
    if not rag_config or rag_config.get("enabled") is False:
        return None

    metadata = turn.metadata if isinstance(turn.metadata, dict) else {}
    if not metadata:
        return None

    try:
        payload = {**metadata, "metadata": metadata}
        evidence = extract_rag_evidence(payload, {"rag_config": rag_config})
        if evidence is not None:
            return evidence
        return _citation_only_rag_evidence(payload, rag_config)
    except Exception:
        return None


def _citation_only_rag_evidence(data: dict[str, Any], rag_config: dict[str, Any]) -> Optional[RAGEvidence]:
    citation_path = rag_config.get("citation_path") or rag_config.get("citations_path")
    if not citation_path:
        return None
    citations = get_values_by_path(data, citation_path)
    if not citations:
        return None
    metadata = {
        key: value
        for key, value in rag_config.items()
        if key not in {"enabled", "context_path", "contexts_path", "retrieved_context_path", "citation_path", "citations_path"}
    }
    return RAGEvidence(
        available=True,
        source=str(rag_config.get("source_type") or rag_config.get("source") or "agent_retrieval"),
        contexts=[],
        citations=citations,
        metadata=metadata or None,
    )


def voice_to_deepeval_test_case(vc: VoiceConversation) -> Any:
    """
    Convert a VoiceConversation directly to a DeepEval ConversationalTestCase.

    Use this when you want to run DeepEval's ConversationalGEval (or future
    voice-specific metrics) against a voice conversation without going through
    NormalizedConversation first.

    Confirmed compatible with deepeval==2.0.9:
        ConversationalTestCase(turns=[LLMTestCase(input=..., actual_output=...)])

    Parameters
    ----------
    vc:
        Fully populated VoiceConversation.

    Returns
    -------
    deepeval.test_case.ConversationalTestCase
    """
    # Deferred import to isolate DeepEval dependency
    from deepeval.test_case import ConversationalTestCase, LLMTestCase

    turns = []
    user_text = ""
    for turn in vc.turns:
        if turn.speaker == Speaker.user:
            user_text = turn.text
        elif turn.speaker == Speaker.agent:
            turns.append(LLMTestCase(
                input=user_text,
                actual_output=turn.text,
            ))
            user_text = ""

    if not turns:
        # Provide a minimal valid test case so DeepEval doesn't reject it
        turns = [LLMTestCase(input="", actual_output="")]

    return ConversationalTestCase(turns=turns)
