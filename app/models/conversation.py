from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field

class RAGEvidence(BaseModel):
    available: bool = False
    source: str = "unknown"
    contexts: list[str] = Field(default_factory=list)
    citations: Optional[list[Any]] = None
    metadata: Optional[dict[str, Any]] = None

class ToolCallInfo(BaseModel):
    tool_name: str
    tool_input: dict[str, Any] | str
    tool_output: Optional[str | dict[str, Any]] = None

class ConversationMessage(BaseModel):
    role: str  # "simulated_user" | "agent" | "system"
    content: str
    turn_index: int
    timestamp: Optional[str] = None
    tool_calls: Optional[list[ToolCallInfo]] = None
    attachments: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None
    rag_evidence: Optional[RAGEvidence] = None

class NormalizedConversation(BaseModel):
    run_id: str
    session_id: str
    channel: str
    messages: list[ConversationMessage]
    retrieval_context: Optional[list[str]] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: str = "completed"
    metadata: Optional[dict[str, Any]] = None
