"""Calling-specific failure analysis built from captured call evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.calling.execution_result import CallingExecutionResult, CallingExecutionStatus
from app.evaluation_service import EvaluationResult
from app.models.failure_analysis import FailureAnalysis


_LAYERS = {
    "AGENT_BEHAVIOR",
    "PERSONA_BEHAVIOR",
    "TURN_TAKING",
    "STT",
    "TTS",
    "PROVIDER",
    "TOOL_BACKEND",
    "EVALUATION_INFRASTRUCTURE",
    "UNKNOWN",
}


@dataclass(frozen=True)
class CallingFailureAnalyzer:
    """Explain failed calling metrics without changing their scores or status."""

    def analyze(
        self,
        evaluation: EvaluationResult,
        execution: CallingExecutionResult,
    ) -> list[FailureAnalysis]:
        conversation = [turn for turn in evaluation.conversation if not _is_system_turn(turn)]
        existing = {
            item.metric_name: item for item in (evaluation.failure_analysis or [])
        }
        analyses: list[FailureAnalysis] = []
        structured_evidence = _structured_evidence(conversation)
        workflow = next((
            (turn.metadata or {}).get("calling_workflow_evidence")
            for turn in conversation if (turn.metadata or {}).get("calling_workflow_evidence")
        ), [])
        for metric in list(evaluation.metrics or []) + list(evaluation.voice_metrics or []):
            if metric.passed or metric.evaluation_status in {"not_evaluated", "error"}:
                continue
            turn = _resolve_turn(metric, conversation)
            layer, confidence, proof = _classify(metric, turn, execution, structured_evidence)
            relevant = [item for item in workflow if item.get("turn_index") == getattr(turn, "turn_index", None)]
            justified = any(item.get("justified_reasks") for item in relevant)
            if justified and metric.name in {"Context Retention", "Answer Relevancy", "Completeness", "Response Quality", "Intent Understanding"}:
                layer, confidence, proof = (
                    "PERSONA_BEHAVIOR", "high",
                    "Chronological calling evidence shows the persona did not supply the requested field. "
                    "The referenced agent re-request concerns unresolved information; it does not prove agent forgetting.",
                )
            base = existing.get(metric.name)
            snippet = _snippet(conversation, turn)
            evidence = [_turn_evidence(turn)] if turn is not None else []
            analyses.append(
                FailureAnalysis(
                    category=layer,
                    source="CallingFailureAnalyzer",
                    metric_name=metric.name,
                    status="FAIL",
                    severity=_severity(metric.score),
                    reason=proof if justified else (metric.reason or "Calling metric failed."),
                    failure_summary=(
                        proof if justified else base.failure_summary if base and base.failure_summary
                        else f"{metric.name} did not meet the configured calling threshold."
                    ),
                    expected=f"Score >= {metric.threshold}" if metric.threshold is not None else None,
                    actual={"score": metric.score, "reason": metric.reason},
                    root_cause=proof,
                    business_impact=base.business_impact if base else None,
                    recommendation=_recommendation(layer),
                    conversation_turn=getattr(turn, "turn_index", None),
                    conversation_message_id=getattr(turn, "conversation_message_id", None),
                    conversation_snippet=snippet or None,
                    evidence=evidence,
                    technical_details={
                        "score": metric.score,
                        "threshold": metric.threshold,
                        "likely_failure_layer": layer,
                        "confidence": confidence,
                        "provider_status": (
                            execution.call_session.status.value
                            if execution.call_session is not None else None
                        ),
                        "call_duration_seconds": execution.duration_seconds,
                        "raw_metric_evidence": metric.evidence or [],
                        "calling_structured_evidence": structured_evidence,
                        "calling_workflow_evidence": relevant,
                    },
                )
            )

        # Backend failures have no MetricResult but remain useful calling evidence.
        for item in evaluation.failure_analysis or []:
            if item.metric_name == "Backend Validation" and item.metric_name not in {
                analysis.metric_name for analysis in analyses
            }:
                analyses.append(item.model_copy(update={
                    "category": "TOOL_BACKEND",
                    "source": "CallingFailureAnalyzer",
                    "technical_details": {
                        **item.technical_details,
                        "likely_failure_layer": "TOOL_BACKEND",
                        "confidence": "high",
                    },
                }))
        return analyses


def _classify(metric: Any, turn: Any, execution: CallingExecutionResult, structured_evidence: list[dict[str, Any]] | None = None) -> tuple[str, str, str]:
    contract_violations = execution.execution_metadata.get("simulator_contract_violations") or []
    if contract_violations:
        return (
            "EVALUATION_INFRASTRUCTURE",
            "high",
            "Captured simulator contract evidence shows the test harness produced an invalid customer turn; this failure cannot be attributed to the agent.",
        )
    text = " ".join(
        str(value or "")
        for value in (metric.name, metric.category, metric.reason, metric.evidence, metric.diagnostics)
    ).lower()
    matched_fields = {
        item.get("field") for item in (structured_evidence or [])
        if item.get("semantic_match") is True
    }
    if matched_fields and any(token in text for token in ("changed", "different", "contradict", "forgot", "mismatch")):
        return (
            "UNKNOWN",
            "high",
            "Deterministic calling evidence proves equivalent normalized values for "
            + ", ".join(sorted(str(field) for field in matched_fields))
            + "; the metric's value-contradiction claim is not supported.",
        )
    if execution.status != CallingExecutionStatus.completed or execution.error:
        layer = "PROVIDER" if execution.call_session is not None else "EVALUATION_INFRASTRUCTURE"
        return layer, "high", f"Captured execution evidence shows a {layer.lower().replace('_', ' ')} failure: {execution.error or execution.status.value}."
    if any(word in text for word in ("backend", "tool call", "webhook", "api action")):
        return "TOOL_BACKEND", "high", "Captured metric evidence identifies a tool or backend action failure."
    if any(word in text for word in ("transcription", "speech-to-text", "stt", "transcript confidence")):
        return "STT", "medium", "Captured metric evidence identifies speech-to-text or transcript quality as the likely failure layer."
    if any(word in text for word in ("pronunciation", "text-to-speech", "tts", "synthesis")):
        return "TTS", "medium", "Captured metric evidence identifies synthesized speech as the likely failure layer."
    if any(word in text for word in ("barge", "interrupt", "turn-taking", "silence", "latency", "incomplete utterance", "repeated question")):
        return "TURN_TAKING", "medium", "Captured metric evidence identifies call timing or turn-taking behavior as the likely failure layer."
    if turn is not None:
        if turn.speaker == "agent":
            return "AGENT_BEHAVIOR", "medium", "The failed metric references a captured agent turn; the evidence does not establish a lower-layer audio fault."
        if turn.speaker == "user":
            return "PERSONA_BEHAVIOR", "medium", "The failed metric references a captured simulated-customer turn; the evidence does not establish an agent fault."
    return "UNKNOWN", "low", "The captured evaluation evidence is insufficient to prove which call layer caused this failure."


def _resolve_turn(metric: Any, conversation: list[Any]) -> Any:
    message_id = getattr(metric, "conversation_message_id", None)
    if message_id:
        return next((turn for turn in conversation if turn.conversation_message_id == message_id), None)
    turn_index = getattr(metric, "turn_index", None)
    if turn_index is None:
        return None
    return next((turn for turn in conversation if turn.turn_index == turn_index), None)


def _is_system_turn(turn: Any) -> bool:
    metadata = getattr(turn, "metadata", None) or {}
    return str(metadata.get("speaker") or "").lower() == "system"


def _turn_evidence(turn: Any) -> dict[str, Any]:
    metadata = getattr(turn, "metadata", None) or {}
    return {
        "type": "calling_transcript_turn",
        "turn": turn.turn_index,
        "role": "customer" if turn.speaker == "user" else "agent",
        "transcript_excerpt": turn.message,
        "timestamp": metadata.get("timestamp"),
        "start_time": metadata.get("start_time"),
        "end_time": metadata.get("end_time"),
        "stt_confidence": metadata.get("confidence"),
    }


def _structured_evidence(conversation: list[Any]) -> list[dict[str, Any]]:
    for turn in conversation:
        metadata = getattr(turn, "metadata", None) or {}
        evidence = metadata.get("calling_structured_evidence")
        if isinstance(evidence, list):
            return [item for item in evidence if isinstance(item, dict)]
    return []


def _snippet(conversation: list[Any], turn: Any) -> list[dict[str, Any]]:
    if turn is None:
        return []
    position = conversation.index(turn)
    return [
        {
            "turn": item.turn_index,
            "speaker": "customer" if item.speaker == "user" else "agent",
            "message": item.message,
            "conversation_message_id": item.conversation_message_id,
        }
        for item in conversation[max(0, position - 1): position + 2]
    ]


def _severity(score: float) -> str:
    if score < 0.4:
        return "high"
    if score < 0.7:
        return "medium"
    return "low"


def _recommendation(layer: str) -> str:
    recommendations = {
        "AGENT_BEHAVIOR": "Review the referenced agent turn against the scenario requirement and adjust the calling agent behavior.",
        "PERSONA_BEHAVIOR": "Review the referenced simulated-customer turn and its scenario grounding before attributing the failure to the agent.",
        "TURN_TAKING": "Inspect utterance boundaries and timing around the referenced exchange.",
        "STT": "Compare the captured audio with the provider transcript before changing agent behavior.",
        "TTS": "Compare the exact simulator text with synthesized audio and the provider transcript.",
        "PROVIDER": "Inspect provider lifecycle and termination evidence for this call.",
        "TOOL_BACKEND": "Inspect the failed tool or backend action using its captured request and response evidence.",
        "EVALUATION_INFRASTRUCTURE": "Inspect the calling execution error and retain the run as an infrastructure failure.",
        "UNKNOWN": "Capture additional turn-level audio or diagnostic evidence before assigning a root cause.",
    }
    return recommendations[layer if layer in _LAYERS else "UNKNOWN"]
