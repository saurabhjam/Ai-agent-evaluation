"""
Backend validation layer.

Every request that reaches the orchestrator/evaluator passes through these
Pydantic models first. This is where malformed scenarios, out-of-range turn
counts, or missing persona fields get rejected with a 422 before any
LLM call (simulator or judge) is made — keeping bad input from silently
burning API quota or producing meaningless scores.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Any

from pydantic import BaseModel, Field, field_validator

from app.config import settings


class Channel(str, Enum):
    chatbot = "chatbot"
    voice = "voice"  # reserved for the voice adapter (Section 4 of the R&D report)


class Persona(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    goal: str = Field(..., min_length=10, max_length=400,
                       description="What the simulated user is trying to accomplish")
    tone: str = Field(..., min_length=3, max_length=60,
                       description="e.g. 'polite but impatient', 'confused first-time user'")
    edge_case: Optional[str] = Field(
        None, max_length=300,
        description="Optional adversarial behavior, e.g. 'changes mind halfway through'"
    )

    @field_validator("goal")
    @classmethod
    def goal_must_be_actionable(cls, v: str) -> str:
        if v.strip().lower() in {"", "n/a", "none"}:
            raise ValueError("persona.goal must describe a concrete objective")
        return v.strip()


class AgentConfig(BaseModel):
    channel: str = "chatbot"
    adapter: str = "fake"
    config: dict[str, Any] = Field(default_factory=dict)

class TestScenario(BaseModel):
    scenario_id: str = Field(..., min_length=3, max_length=80)
    agent: AgentConfig
    persona: Persona
    steps: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description="Optional explicit chatbot steps, e.g. send/click_button actions.",
    )
    max_turns: int = Field(default=20, ge=settings.min_turns_per_run, le=settings.max_turns_per_run)
    pass_threshold: float = Field(
        default=0.7, ge=0.0, le=1.0,
        description="Minimum average judge score required to mark the run as PASS"
    )
    rag_context: Optional[list[str]] = Field(
        default=None,
        description="Optional ground-truth context, enables hallucination/faithfulness checks"
    )
    agent_prompt: Optional[str] = Field(
        default=None,
        description="Optional system prompt to make the reference agent scenario-aware"
    )
    backend_validation: Optional[list[dict[str, Any]] | dict[str, Any]] = Field(
        default=None,
        description="Optional backend validation rules. Backend connection details live on AgentConnection.",
    )

    @field_validator("max_turns")
    @classmethod
    def turns_within_bounds(cls, v: int) -> int:
        if v > settings.max_turns_per_run:
            raise ValueError(
                f"max_turns ({v}) exceeds platform limit ({settings.max_turns_per_run}) "
                "— raise MAX_TURNS_PER_RUN in .env if this is intentional"
            )
        return v

class MetricResult(BaseModel):
    name: str
    description: Optional[str] = None
    score: float = Field(..., ge=0.0, le=1.0)
    reason: str
    passed: bool
    threshold: Optional[float] = None
    category: Optional[str] = None
    evidence_source: Optional[str] = None
    turn_index: Optional[int] = None
    conversation_message_id: Optional[str] = None
    evaluation_status: Optional[str] = None
    evidence_status: Optional[str] = None
    evidence: Optional[list[dict[str, Any]]] = None
    diagnostics: Optional[dict[str, Any]] = None


class RAGEvaluationSummary(BaseModel):
    status: str
    evidence_source: Optional[str] = None
    context_count: int = 0
    rag_score: Optional[float] = None
    reason: Optional[str] = None


class TestRunResult(BaseModel):
    run_id: str
    scenario_id: str
    agent: AgentConfig
    transcript: list[Any]
    metrics: list[MetricResult]
    voice_metrics: Optional[list[MetricResult]] = None
    rag_evaluation: Optional[RAGEvaluationSummary] = None
    overall_score: float
    passed: bool
    created_at: str


class TestRunRequest(BaseModel):
    scenario: TestScenario
    agent_override: Optional[dict[str, Any]] = None
