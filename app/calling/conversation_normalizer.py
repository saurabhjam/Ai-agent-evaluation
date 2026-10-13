"""Normalize ConversationEvidence into EvalForge's shared conversation model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.calling.conversation_evidence import ConversationEvidence
from app.calling.normalizer import call_transcript_to_normalized_conversation
from app.models.conversation import NormalizedConversation


@dataclass(frozen=True)
class ConversationNormalizer:
    """Converts provider-neutral calling evidence to NormalizedConversation."""

    def normalize(
        self,
        evidence: ConversationEvidence,
        *,
        scenario_id: Optional[str] = None,
        rag_config: Optional[dict[str, Any]] = None,
    ) -> NormalizedConversation:
        """Convert evidence to the existing evaluation input model."""
        normalized = call_transcript_to_normalized_conversation(
            evidence.effective_transcript(),
            scenario_id=scenario_id,
            retrieval_context=evidence.rag_context,
            rag_config=rag_config,
        )
        metadata = {
            **(normalized.metadata or {}),
            "evidence_id": evidence.evidence_id,
            "provider": evidence.provider.value,
            "provider_name": evidence.provider_name,
            "provider_call_id": evidence.provider_call_id,
            "recording_count": len(evidence.recordings),
            "event_count": len(evidence.events),
            "attachment_count": len(evidence.attachments),
            "started_at": evidence.started_at,
            "connected_at": evidence.connected_at,
            "ended_at": evidence.ended_at,
            **evidence.metadata,
        }
        return normalized.model_copy(update={"metadata": metadata})
