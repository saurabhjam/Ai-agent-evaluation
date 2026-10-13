"""Convert calling transcript evidence into the shared conversation model."""

from __future__ import annotations

from typing import Any, Optional

from app.calling.models import RawCallTranscript, TranscriptSpeaker
from app.models.conversation import ConversationMessage, NormalizedConversation, RAGEvidence
from app.rag import extract_rag_evidence, get_values_by_path


def call_transcript_to_normalized_conversation(
    transcript: RawCallTranscript,
    *,
    scenario_id: Optional[str] = None,
    retrieval_context: Optional[list[str]] = None,
    rag_config: Optional[dict[str, Any]] = None,
) -> NormalizedConversation:
    """
    Convert a calling transcript to the shared evaluator input shape.

    DeepEval and the existing evaluation service should consume only this
    normalized evidence, not provider-specific calling models.
    """
    role_map = {
        TranscriptSpeaker.customer: "simulated_user",
        TranscriptSpeaker.agent: "agent",
        TranscriptSpeaker.system: "system",
    }

    messages: list[ConversationMessage] = []
    for turn in transcript.turns:
        rag_evidence = _turn_rag_evidence(turn, rag_config)
        messages.append(
            ConversationMessage(
                role=role_map.get(turn.speaker, "system"),
                content=turn.text,
                turn_index=turn.turn_index,
                timestamp=turn.timestamp,
                metadata={
                    "source": transcript.source,
                    "speaker": turn.speaker.value,
                    "start_time": turn.start_time,
                    "end_time": turn.end_time,
                    "confidence": turn.confidence,
                    "audio_path": turn.audio_path,
                    **turn.metadata,
                },
                rag_evidence=rag_evidence,
            )
        )

    metadata = {
        "channel": "calling",
        "source": transcript.source,
        "language": transcript.language,
        **transcript.metadata,
    }
    if scenario_id is not None:
        metadata["scenario_id"] = scenario_id

    return NormalizedConversation(
        run_id=transcript.run_id,
        session_id=transcript.session_id,
        channel="calling",
        messages=messages,
        retrieval_context=retrieval_context,
        status="completed",
        metadata=metadata,
    )


def _turn_rag_evidence(turn: Any, rag_config: Optional[dict[str, Any]]) -> Optional[RAGEvidence]:
    if getattr(turn, "speaker", None) != TranscriptSpeaker.agent:
        return None
    if not rag_config or rag_config.get("enabled") is False:
        return None

    metadata = turn.metadata if isinstance(getattr(turn, "metadata", None), dict) else {}
    if not metadata:
        return None

    try:
        evidence = extract_rag_evidence(metadata, {"rag_config": rag_config})
        if evidence is not None:
            return evidence
        return _citation_only_rag_evidence(metadata, rag_config)
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
