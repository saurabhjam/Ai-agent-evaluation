"""
Evaluation Service Layer.

Accepts an ExecutionResult and routes it through the existing evaluator and metrics modules.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from typing import Literal
from app.backend_validation import BackendValidationEngine, BackendValidationSummary, backend_validation_engine
from app.failure_analysis import FailureAnalysisEngine, failure_analysis_engine
from app.models.conversation import RAGEvidence
from app.models.failure_analysis import FailureAnalysis
from app.workflow_models import ScenarioMetadata
from app.evaluation_evidence import TechnicalErrorEvidence, classify_technical_errors

class ConversationTurn(BaseModel):
    turn_index: int = 0
    conversation_message_id: str = ""
    message_id: str = ""
    id: str = ""
    speaker: Literal["user", "agent"]
    message: str
    attachments: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None
    tool_calls: Optional[list[dict[str, Any]]] = None
    components: Optional[list[dict[str, Any]]] = None
    rag: Optional[RAGEvidence] = None


from app.executor import ExecutionResult
from app.schemas import TestScenario, MetricResult, RAGEvaluationSummary
from app.evaluator import evaluate_transcript
from app.models.connection import AgentType
from app.voice.metrics import run_voice_metrics
from app.workflow_metrics import run_workflow_metrics

from app.voice.config import VoiceMetricsConfig

logger = logging.getLogger(__name__)


class EvaluationResult(BaseModel):
    """
    Unified result of an evaluation run.
    """
    evaluation_id: Optional[str] = None
    success: bool
    agent_id: str
    agent_type: str
    adapter: str
    scenario_id: str
    scenario_metadata: Optional[ScenarioMetadata] = None
    session_id: Optional[str] = None
    overall_score: float = 0.0
    passed: bool = False
    conversation: list[ConversationTurn] = Field(default_factory=list)
    metrics: list[MetricResult] = Field(default_factory=list)
    voice_metrics: Optional[list[MetricResult]] = None
    rag_evaluation: Optional[RAGEvaluationSummary] = None
    backend_validation: Optional[BackendValidationSummary] = None
    failure_analysis: Optional[list[FailureAnalysis]] = None
    technical_errors: Optional[list[TechnicalErrorEvidence]] = None
    error: Optional[str] = None
    created_at: str


class EvaluationService:
    """
    Orchestrates evaluation.
    """
    def __init__(
        self,
        backend_validation_engine: Optional[BackendValidationEngine] = None,
        failure_analysis_engine: Optional[FailureAnalysisEngine] = None,
    ):
        self.backend_validation_engine = backend_validation_engine or globals()["backend_validation_engine"]
        self.failure_analysis_engine = failure_analysis_engine or globals()["failure_analysis_engine"]

    def evaluate(self, execution_result: ExecutionResult, scenario: TestScenario) -> EvaluationResult:
        created_at = datetime.now(timezone.utc).isoformat()
        
        if not execution_result.success:
            technical_errors = classify_technical_errors(execution_error=execution_result.error)
            return EvaluationResult(
                success=False,
                agent_id=execution_result.connection_id,
                agent_type=execution_result.agent_type,
                adapter=execution_result.adapter,
                scenario_id=scenario.scenario_id,
                session_id=execution_result.session_id,
                error=f"Cannot evaluate: execution failed. Reason: {execution_result.error}",
                technical_errors=technical_errors or None,
                created_at=created_at,
            )

        try:
            transcript = execution_result.transcript or []
            if not transcript:
                return EvaluationResult(
                    success=False,
                    agent_id=execution_result.connection_id,
                    agent_type=execution_result.agent_type,
                    adapter=execution_result.adapter,
                    scenario_id=scenario.scenario_id,
                    session_id=execution_result.session_id,
                    error="No conversation evidence was captured.",
                    created_at=created_at,
                )
            _ensure_transcript_message_identity(transcript)
            
            rag_evidence_by_turn = _rag_evidence_by_turn(transcript)
            rag_evaluation = _resolve_rag_status(rag_evidence_by_turn, scenario.rag_context)
            technical_errors = classify_technical_errors(transcript=transcript)

            # 1. Base Evaluation (DeepEval metrics)
            metrics = evaluate_transcript(
                persona=scenario.persona,
                transcript=transcript,
                rag_context=None if rag_evidence_by_turn else scenario.rag_context,
                rag_evidence_by_turn=rag_evidence_by_turn or None,
                expected_agent_persona=_expected_agent_persona(scenario),
            )
            
            # Extract conversation for report/UI rendering. Keep the existing
            # speaker/message shape while preserving adapter-captured rich
            # evidence as optional presentation data.
            conversation: list[ConversationTurn] = []
            for index, msg in enumerate(transcript):
                role = _message_value(msg, "role")
                content = _message_value(msg, "content") or ""
                attachments = _message_value(msg, "attachments") or []
                metadata = _message_value(msg, "metadata") or {}
                tool_calls = _message_value(msg, "tool_calls") or []
                rag = _message_value(msg, "rag_evidence")
                speaker: Literal["user", "agent"] = "user" if role == "simulated_user" else "agent"
                turn_index = _message_turn_index(msg, index)
                message_id = _message_identity(msg, turn_index)
                conversation.append(
                    ConversationTurn(
                        turn_index=turn_index,
                        conversation_message_id=message_id,
                        message_id=message_id,
                        id=message_id,
                        speaker=speaker,
                        message=str(content),
                        attachments=list(attachments) if isinstance(attachments, list) and attachments else None,
                        metadata=dict(metadata) if isinstance(metadata, dict) and metadata else None,
                        tool_calls=_serialise_tool_calls(tool_calls) or None,
                        components=_conversation_components(metadata) or None,
                        rag=rag if isinstance(rag, RAGEvidence) else None,
                    )
                )
            
            # 2. Voice Metrics
            voice_metrics = None
            if execution_result.agent_type == AgentType.voice.value and execution_result.voice_conversation:
                # Reuse existing voice metrics
                # We assume scenario configuration for voice metrics is passed somehow, or defaults.
                # In a real app this would come from scenario, here we use defaults if missing.
                # Just mock an empty config for now, or you could pass scenario.voice.metrics.
                # Since TestScenario schema doesn't strictly have a `voice` field at top level, 
                # we'll use a default VoiceMetricsConfig.
                voice_config = VoiceMetricsConfig()
                voice_metrics = run_voice_metrics(execution_result.voice_conversation, voice_config)
            
            # 3. Workflow Metrics
            workflow_metrics = run_workflow_metrics(transcript)
            metrics.extend(workflow_metrics)

            # 4. Backend validation is independent post-processing. It must not
            # affect scoring, metrics, execution, or adapter behavior.
            backend_validation = self.backend_validation_engine.validate(transcript, scenario)

            # 5. Final Scoring
            # Balance evaluation categories so multiple RAG turns do not
            # automatically dominate conversation-level quality metrics.
            overall_score = _balanced_overall_score(metrics)
            rag_score = _metric_average(_rag_metrics(metrics))
            if rag_score is not None and rag_evaluation.status == "evaluated":
                rag_evaluation.rag_score = rag_score
            
            passed = overall_score >= scenario.pass_threshold
            failure_analysis = self.failure_analysis_engine.generate(
                metrics=metrics,
                voice_metrics=voice_metrics,
                backend_validation=backend_validation,
                transcript=transcript,
                conversation=conversation,
                scenario=scenario,
            )
            
            return EvaluationResult(
                success=True,
                agent_id=execution_result.connection_id,
                agent_type=execution_result.agent_type,
                adapter=execution_result.adapter,
                scenario_id=scenario.scenario_id,
                session_id=execution_result.session_id,
                overall_score=overall_score,
                passed=passed,
                conversation=conversation,
                metrics=metrics,
                voice_metrics=voice_metrics,
                rag_evaluation=rag_evaluation,
                backend_validation=backend_validation,
                failure_analysis=failure_analysis or None,
                technical_errors=technical_errors or None,
                created_at=created_at,
            )

        except Exception as e:
            logger.exception("Evaluation failed")
            return EvaluationResult(
                success=False,
                agent_id=execution_result.connection_id,
                agent_type=execution_result.agent_type,
                adapter=execution_result.adapter,
                scenario_id=scenario.scenario_id,
                session_id=execution_result.session_id,
                error=f"Evaluation failed: {e}",
                created_at=created_at,
            )


def _expected_agent_persona(scenario: TestScenario) -> Any:
    config = getattr(getattr(scenario, "agent", None), "config", None)
    if not isinstance(config, dict):
        return None
    for key in ("expected_agent_persona", "agent_persona", "expected_agent_behavior"):
        if config.get(key) not in (None, "", {}, []):
            return config[key]
    expected_tone = config.get("expected_agent_tone")
    return {"tone": expected_tone} if expected_tone else None


def _message_value(message: Any, key: str) -> Any:
    if isinstance(message, dict):
        return message.get(key)
    return getattr(message, key, None)


def _ensure_transcript_message_identity(transcript: list[Any]) -> None:
    for index, msg in enumerate(transcript):
        original_turn_index = _message_value(msg, "turn_index")
        turn_index = index
        message_id = _message_identity(msg, index)
        metadata = _message_value(msg, "metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["conversation_message_id"] = message_id
        metadata["message_id"] = message_id
        metadata["turn_index"] = turn_index
        if isinstance(original_turn_index, int) and original_turn_index != turn_index:
            metadata.setdefault("original_turn_index", original_turn_index)

        if isinstance(msg, dict):
            msg["turn_index"] = turn_index
            msg["conversation_message_id"] = message_id
            msg["message_id"] = message_id
            msg["id"] = message_id
            msg["metadata"] = metadata
        else:
            setattr(msg, "turn_index", turn_index)
            setattr(msg, "metadata", metadata)
            for attr in ("conversation_message_id", "message_id", "id"):
                try:
                    setattr(msg, attr, message_id)
                except Exception:
                    pass


def _message_turn_index(message: Any, fallback: int) -> int:
    value = _message_value(message, "turn_index")
    return value if isinstance(value, int) else fallback


def _message_identity(message: Any, message_index: int) -> str:
    existing = (
        _message_value(message, "conversation_message_id")
        or _message_value(message, "message_id")
        or _message_value(message, "id")
    )
    if existing and not _is_generated_turn_id(existing):
        return str(existing)
    metadata = _message_value(message, "metadata")
    if isinstance(metadata, dict):
        existing = metadata.get("conversation_message_id") or metadata.get("message_id") or metadata.get("id")
        if existing and not _is_generated_turn_id(existing):
            return str(existing)
    return f"ef-message-{message_index}"


def _is_generated_turn_id(value: Any) -> bool:
    return str(value or "").startswith("ef-turn-")


def _serialise_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
    if not isinstance(tool_calls, list):
        return []
    serialised: list[dict[str, Any]] = []
    for call in tool_calls:
        if isinstance(call, dict):
            serialised.append(call)
        elif hasattr(call, "model_dump"):
            serialised.append(call.model_dump(mode="json"))
        else:
            serialised.append({
                "tool_name": getattr(call, "tool_name", "tool"),
                "tool_input": getattr(call, "tool_input", None),
                "tool_output": getattr(call, "tool_output", None),
            })
    return serialised


def _conversation_components(
    metadata: Any,
) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    metadata = metadata if isinstance(metadata, dict) else {}

    for key in ("components", "rich_components"):
        raw_components = metadata.get(key)
        if isinstance(raw_components, list):
            components.extend([item for item in raw_components if isinstance(item, dict)])

    return components


def _rag_evidence_by_turn(transcript: list[Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    last_user_message = ""

    for msg in transcript:
        role = _message_value(msg, "role")
        content = str(_message_value(msg, "content") or "")
        if role in {"simulated_user", "user"}:
            last_user_message = content
            continue

        if role != "agent":
            continue

        rag = _message_value(msg, "rag_evidence")
        if not isinstance(rag, RAGEvidence):
            continue
        if not rag.available or not rag.contexts:
            continue

        contexts = [ctx for ctx in rag.contexts if isinstance(ctx, str) and ctx.strip()]
        if not contexts:
            continue

        evidence.append(
            {
                "input": last_user_message,
                "actual_output": content,
                "contexts": contexts,
                "source": rag.source,
                "citations": rag.citations,
                "turn_index": _message_turn_index(msg, len(evidence)),
                "conversation_message_id": _message_identity(msg, _message_turn_index(msg, len(evidence))),
            }
        )

    return evidence


def _resolve_rag_status(
    rag_evidence_by_turn: list[dict[str, Any]],
    scenario_rag_context: Optional[list[str]],
) -> RAGEvaluationSummary:
    if rag_evidence_by_turn:
        context_count = sum(len(item.get("contexts") or []) for item in rag_evidence_by_turn)
        return RAGEvaluationSummary(
            status="evaluated",
            evidence_source="agent_retrieval",
            context_count=context_count,
        )

    reference_context = [ctx for ctx in (scenario_rag_context or []) if isinstance(ctx, str) and ctx.strip()]
    if reference_context:
        return RAGEvaluationSummary(
            status="evaluated",
            evidence_source="reference_context",
            context_count=len(reference_context),
        )

    return RAGEvaluationSummary(
        status="not_evaluated",
        reason="RAG evidence was not exposed by the agent and no reference context was provided.",
    )


def _rag_metrics(metrics: list[MetricResult]) -> list[MetricResult]:
    return [
        metric for metric in metrics
        if metric.category == "rag" or metric.evidence_source in {"agent_retrieval", "reference_context"}
    ]


def _base_metrics(metrics: list[MetricResult]) -> list[MetricResult]:
    rag_ids = {id(metric) for metric in _rag_metrics(metrics)}
    return [metric for metric in metrics if id(metric) not in rag_ids]


def _metric_average(metrics: list[MetricResult]) -> Optional[float]:
    metrics = [metric for metric in metrics if metric.evaluation_status not in {"not_evaluated", "error"}]
    if not metrics:
        return None
    return round(sum(metric.score for metric in metrics) / len(metrics), 3)


def _balanced_overall_score(metrics: list[MetricResult]) -> float:
    category_scores = [
        score for score in (
            _metric_average(_base_metrics(metrics)),
            _metric_average(_rag_metrics(metrics)),
        )
        if score is not None
    ]
    if not category_scores:
        return 0.0
    return round(sum(category_scores) / len(category_scores), 3)
