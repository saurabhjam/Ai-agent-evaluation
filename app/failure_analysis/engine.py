"""Enterprise failure analysis generation engine."""

from __future__ import annotations

from typing import Any

from app.backend_validation.models import BackendValidationSummary
from app.failure_analysis.registry import FailureAnalysisRegistry
from app.models.failure_analysis import FailureAnalysis


class FailureAnalysisEngine:
    """
    Generates structured failure explanations from completed evaluation data.

    The engine is post-processing only: it never changes scores, pass/fail
    status, metrics, execution behavior, or validator behavior.
    """

    def __init__(self, registry: FailureAnalysisRegistry | None = None) -> None:
        self.registry = registry or FailureAnalysisRegistry()
        self._register_defaults()

    def register_generator(self, category: str, generator) -> None:
        self.registry.register_generator(category, generator)

    def generate(
        self,
        *,
        metrics: list[Any] | None = None,
        voice_metrics: list[Any] | None = None,
        backend_validation: BackendValidationSummary | None = None,
        transcript: list[Any] | None = None,
        conversation: list[Any] | None = None,
        scenario: Any = None,
    ) -> list[FailureAnalysis]:
        context = {
            "transcript": transcript or [],
            "conversation": conversation or [],
            "scenario": scenario,
            "backend_validation": backend_validation,
        }
        analyses: list[FailureAnalysis] = []

        for metric in list(metrics or []) + list(voice_metrics or []):
            if _metric_passed(metric):
                continue
            category = _metric_category(metric)
            generator = self.registry.get(category) or self.registry.get("unknown")
            if generator:
                analyses.append(generator(metric, context))

        if backend_validation and backend_validation.passed is False:
            generator = self.registry.get("backend validation") or self.registry.get("unknown")
            analyses.append(generator(backend_validation, context))

        return analyses

    def _register_defaults(self) -> None:
        self.register_generator("intent detection", generate_intent_failure)
        self.register_generator("workflow validation", generate_workflow_failure)
        self.register_generator("workflow", generate_workflow_failure)
        self.register_generator("backend validation", generate_backend_failure)
        self.register_generator("ui validation", generate_ui_failure)
        self.register_generator("response validation", generate_response_failure)
        self.register_generator("rag validation", generate_rag_failure)
        self.register_generator("rag", generate_rag_failure)
        self.register_generator("safety validation", generate_safety_failure)
        self.register_generator("conversation validation", generate_conversation_failure)
        self.register_generator("base", generate_conversation_failure)
        self.register_generator("unknown", generate_unknown_failure)


def generate_intent_failure(metric: Any, context: dict[str, Any]) -> FailureAnalysis:
    return _metric_failure(
        metric,
        context,
        root_cause=_root_cause(metric, context, "intent"),
        recommendation=_recommendation(metric, "intent"),
        expected=_expected(metric, "intent"),
    )


def generate_workflow_failure(metric: Any, context: dict[str, Any]) -> FailureAnalysis:
    evidence = _workflow_evidence(context, _turn_index(metric))
    return _metric_failure(
        metric,
        context,
        root_cause=_root_cause(metric, context, "workflow"),
        recommendation=_recommendation(metric, "workflow"),
        expected=_expected(metric, "workflow"),
        evidence=evidence,
    )


def generate_backend_failure(summary: Any, context: dict[str, Any]) -> FailureAnalysis:
    failed_checks = [
        check for check in getattr(summary, "checks", []) or []
        if getattr(check, "passed", None) is False
    ]
    evidence = []
    for check in failed_checks:
        evidence.append({
            "type": "backend_validation_evidence",
            "title": getattr(check, "name", None) or "Backend validation check",
            "name": getattr(check, "name", None),
            "expected": getattr(check, "expected", None),
            "actual": getattr(check, "actual", None),
            "reason": getattr(check, "reason", None),
            "why_this_proves_failure": getattr(check, "reason", None) or "The backend state did not match the expected validation rule.",
        })

    copy = _backend_failure_copy()
    return FailureAnalysis(
        metric_name="Backend Validation",
        category="Backend Validation",
        source="BackendValidationEngine",
        status=str(getattr(summary, "status", "FAIL") or "FAIL").upper(),
        severity="high",
        reason=str(getattr(summary, "reason", "") or "Backend validation failed."),
        failure_summary=copy["summary"],
        expected=[getattr(check, "expected", None) for check in failed_checks] or None,
        actual=[getattr(check, "actual", None) for check in failed_checks] or None,
        root_cause=copy["root_cause"],
        business_impact=copy["business_impact"],
        recommendation=copy["recommendation"],
        evidence=evidence,
        technical_details={"checks": [_model_dump(check) for check in getattr(summary, "checks", []) or []]},
    )


def generate_ui_failure(metric: Any, context: dict[str, Any]) -> FailureAnalysis:
    evidence = _workflow_evidence(context, _turn_index(metric))
    return _metric_failure(
        metric,
        context,
        root_cause=_root_cause(metric, context, "ui"),
        recommendation=_recommendation(metric, "ui"),
        expected=_expected(metric, "ui"),
        evidence=evidence,
    )


def generate_response_failure(metric: Any, context: dict[str, Any]) -> FailureAnalysis:
    return _metric_failure(
        metric,
        context,
        root_cause=_root_cause(metric, context, "response"),
        recommendation=_recommendation(metric, "response"),
        expected=_expected(metric, "response"),
    )


def generate_rag_failure(metric: Any, context: dict[str, Any]) -> FailureAnalysis:
    turn = _turn_index(metric)
    evidence = []
    for item in context.get("transcript") or []:
        if turn is not None and _message_value(item, "turn_index") != turn:
            continue
        rag = _message_value(item, "rag_evidence")
        if rag:
            evidence.append(_model_dump(rag))
    return _metric_failure(
        metric,
        context,
        root_cause=_root_cause(metric, context, "rag"),
        recommendation=_recommendation(metric, "rag"),
        expected=_expected(metric, "rag"),
        evidence=evidence,
    )


def generate_safety_failure(metric: Any, context: dict[str, Any]) -> FailureAnalysis:
    return _metric_failure(
        metric,
        context,
        root_cause=_root_cause(metric, context, "safety"),
        recommendation=_recommendation(metric, "safety"),
        expected=_expected(metric, "safety"),
    )


def generate_conversation_failure(metric: Any, context: dict[str, Any]) -> FailureAnalysis:
    return _metric_failure(
        metric,
        context,
        root_cause=_root_cause(metric, context, "conversation"),
        recommendation=_recommendation(metric, "conversation"),
        expected=_expected(metric, "conversation"),
    )


def generate_unknown_failure(metric: Any, context: dict[str, Any]) -> FailureAnalysis:
    return _metric_failure(
        metric,
        context,
        root_cause=_root_cause(metric, context, "unknown"),
        recommendation=_recommendation(metric, "unknown"),
        expected=_expected(metric, "unknown"),
    )


def _metric_failure(
    metric: Any,
    context: dict[str, Any],
    *,
    root_cause: str,
    recommendation: str,
    expected: Any = None,
    evidence: list[Any] | None = None,
) -> FailureAnalysis:
    message_id = _metric_message_id(metric)
    turn = _turn_index(metric)
    if turn is None and message_id:
        turn = _turn_index_for_message(context.get("conversation") or [], message_id)
    if turn is None and context.get("conversation"):
        turn = len(context.get("conversation") or []) - 1
    snippet = _conversation_snippet(context.get("conversation") or [], turn)
    failed_turn = _failed_turn(snippet)
    copy = _failure_copy(metric, failed_turn)
    business_evidence = _business_evidence(metric, snippet, copy["conversation_card"])
    raw_evidence = evidence or _metric_evidence(metric, context)
    return FailureAnalysis(
        category=_failure_category_label(metric),
        source=_failure_source(metric),
        metric_name=str(getattr(metric, "name", "Unknown Metric") or "Unknown Metric"),
        status="FAIL",
        severity=_severity(metric),
        reason=str(getattr(metric, "reason", "") or "Metric failed."),
        failure_summary=copy["summary"],
        expected=expected if expected is not None else _expected_from_metric(metric),
        actual=_actual_from_metric(metric, failed_turn),
        root_cause=copy["root_cause"] or root_cause,
        business_impact=copy["business_impact"],
        recommendation=copy["recommendation"] or recommendation,
        conversation_turn=turn,
        conversation_message_id=message_id or _message_id_from_snippet(snippet, turn),
        conversation_snippet=snippet or None,
        evidence=business_evidence,
        technical_details={
            "score": getattr(metric, "score", None),
            "threshold": getattr(metric, "threshold", None),
            "category": getattr(metric, "category", None),
            "evidence_source": getattr(metric, "evidence_source", None),
            "conversation_message_refs": _conversation_message_refs(snippet),
            "raw_evaluator_reason": getattr(metric, "reason", None),
            "raw_metric_evidence": raw_evidence,
            "raw_conversation_snippet": snippet,
        },
    )


def _metric_passed(metric: Any) -> bool:
    return bool(getattr(metric, "passed", False))


def _metric_category(metric: Any) -> str:
    name = str(getattr(metric, "name", "") or "").lower()
    category = str(getattr(metric, "category", "") or "").lower()
    combined = f"{category} {name}"
    if "intent" in combined:
        return "intent detection"
    if "backend" in combined:
        return "backend validation"
    if "ui validation" in combined or "missing form" in combined or "upload control" in combined:
        return "ui validation"
    if "workflow" in combined or category == "workflow" or any(word in combined for word in ("form", "otp", "upload", "handoff")):
        return "workflow validation"
    if "rag" in combined or category == "rag" or "faithfulness" in combined or "hallucination" in combined:
        return "rag validation"
    if "safety" in combined or "unsafe" in combined:
        return "safety validation"
    if "response" in combined or "relevancy" in combined:
        return "response validation"
    if "conversation" in combined or "persona" in combined or "tone" in combined or "goal" in combined:
        return "conversation validation"
    return category or "unknown"


def _failure_category_label(metric: Any) -> str:
    category = _metric_category(metric)
    labels = {
        "intent detection": "Intent",
        "workflow validation": "Workflow Validation",
        "backend validation": "Backend Validation",
        "ui validation": "UI Validation",
        "response validation": "Response Validation",
        "rag validation": "RAG Validation",
        "safety validation": "Safety Validation",
        "conversation validation": "Conversation Validation",
        "base": "Conversation Validation",
        "unknown": "Unknown",
    }
    return labels.get(category, category.title())


def _failure_source(metric: Any) -> str:
    category = _metric_category(metric)
    sources = {
        "intent detection": "IntentEvaluator",
        "workflow validation": "WorkflowMetrics",
        "backend validation": "BackendValidationEngine",
        "ui validation": "UIValidation",
        "response validation": "ResponseEvaluator",
        "rag validation": "RAGEvaluator",
        "safety validation": "SafetyEvaluator",
        "conversation validation": "ConversationEvaluator",
        "base": "ConversationEvaluator",
    }
    return sources.get(category, "FailureAnalysisEngine")


def _turn_index(metric: Any) -> int | None:
    value = getattr(metric, "turn_index", None)
    return value if isinstance(value, int) else None


def _metric_message_id(metric: Any) -> str | None:
    value = getattr(metric, "conversation_message_id", None)
    return str(value) if value else None


def _severity(metric: Any) -> str:
    score = getattr(metric, "score", None)
    try:
        score_value = float(score)
    except (TypeError, ValueError):
        score_value = 0.0
    if score_value <= 0.25:
        return "high"
    if score_value <= 0.6:
        return "medium"
    return "low"


def _conversation_snippet(conversation: list[Any], turn: int | None) -> list[dict[str, Any]]:
    if turn is None or not conversation:
        return []
    snippet: list[dict[str, Any]] = []
    for idx in range(max(0, turn - 1), min(len(conversation), turn + 2)):
        msg = conversation[idx]
        snippet.append({
            "label": "Failure Turn" if idx == turn else ("Previous Turn" if idx < turn else "Next Turn"),
            "turn": idx,
            "speaker": _message_value(msg, "speaker"),
            "message": _message_value(msg, "message"),
            "conversation_message_id": _message_id(msg),
            "message_id": _message_id(msg),
        })
    return snippet


def _message_id_from_snippet(snippet: list[dict[str, Any]], turn: int | None) -> str | None:
    for item in snippet or []:
        if item.get("turn") == turn and (item.get("conversation_message_id") or item.get("message_id")):
            return str(item.get("conversation_message_id") or item.get("message_id"))
    return None


def _turn_index_for_message(conversation: list[Any], message_id: str) -> int | None:
    for index, message in enumerate(conversation or []):
        if _message_id(message) == message_id:
            value = _message_value(message, "turn_index")
            return value if isinstance(value, int) else index
    return None


def _metric_evidence(metric: Any, context: dict[str, Any]) -> list[Any]:
    evidence = []
    turn = _turn_index(metric)
    if turn is not None:
        for msg in context.get("conversation") or []:
            message_turn = _message_value(msg, "turn_index")
            if isinstance(message_turn, int) and message_turn != turn:
                continue
            if _message_value(msg, "metadata"):
                evidence.append(_message_value(msg, "metadata"))
    return evidence[:3]


def _workflow_evidence(context: dict[str, Any], turn: int | None) -> list[Any]:
    evidence = []
    for msg in context.get("transcript") or []:
        if turn is not None and _message_value(msg, "turn_index") != turn:
            continue
        metadata = _message_value(msg, "metadata")
        if isinstance(metadata, dict) and metadata.get("interaction_evidence"):
            evidence.append(metadata["interaction_evidence"])
    return evidence


def _failed_turn(snippet: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in snippet or []:
        if item.get("label") == "Failure Turn":
            return item
    return None


def _business_evidence(metric: Any, snippet: list[dict[str, Any]], root_cause: str) -> list[dict[str, Any]]:
    if not snippet:
        return []
    previous_turn = _turn_summary_text(_snippet_by_label(snippet, "Previous Turn"))
    failed_turn = _turn_summary_text(_snippet_by_label(snippet, "Failure Turn"))
    next_turn = _turn_summary_text(_snippet_by_label(snippet, "Next Turn"))
    evidence = [{
        "type": "conversation_card",
        "title": f"{getattr(metric, 'name', 'Metric')} failure evidence",
        "previous_turn": previous_turn or "N/A",
        "failed_turn": failed_turn or "N/A",
        "next_turn": next_turn or "N/A",
        "why_this_proves_failure": root_cause,
    }]
    return evidence


def _snippet_by_label(snippet: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    for item in snippet or []:
        if item.get("label") == label:
            return item
    return None


def _turn_summary(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    return {
        "turn": item.get("turn"),
        "speaker": item.get("speaker"),
        "message": item.get("message"),
    }


def _turn_summary_text(item: dict[str, Any] | None) -> str | None:
    if not item:
        return None
    speaker = str(item.get("speaker") or "Unknown").title()
    message = str(item.get("message") or "").strip()
    turn = item.get("turn")
    return f"Turn {turn} - {speaker}: {message}" if message else f"Turn {turn} - {speaker}"


def _conversation_message_refs(snippet: list[dict[str, Any]]) -> dict[str, Any]:
    refs: dict[str, Any] = {}
    for label, key in (
        ("Previous Turn", "previous_turn"),
        ("Failure Turn", "failure_turn"),
        ("Next Turn", "next_turn"),
    ):
        item = _snippet_by_label(snippet, label)
        if not item:
            continue
        refs[key] = {
            "turn": item.get("turn"),
            "message_id": item.get("message_id") or item.get("conversation_message_id"),
            "speaker": item.get("speaker"),
        }
    return refs


def _metric_kind(metric: Any) -> str:
    name = str(getattr(metric, "name", "") or "").lower()
    category = str(getattr(metric, "category", "") or "").lower()
    combined = f"{category} {name}"
    if "grounded" in combined or "groundedness" in combined:
        return "groundedness"
    if "hallucination" in combined:
        return "hallucination"
    if "multi-turn" in combined or "multiturn" in combined or "consistency" in combined:
        return "multi_turn"
    if "context retention" in combined or "context" in combined or "memory" in combined:
        return "context"
    if "conversation quality" in combined:
        return "conversation_quality"
    if "response quality" in combined:
        return "response_quality"
    if "tone" in combined:
        return "tone"
    if "intent" in combined:
        return "intent"
    if "backend" in combined:
        return "backend"
    if "persona" in combined:
        return "persona"
    if "ui" in combined:
        return "ui"
    if "workflow" in combined or any(word in combined for word in ("form", "otp", "upload", "handoff")):
        return "workflow"
    if "complete" in combined or "completion" in combined or "goal" in combined:
        return "completeness"
    if "relevancy" in combined or "relevance" in combined or "answer" in combined:
        return "relevancy"
    if "response" in combined or "quality" in combined:
        return "response"
    if "rag" in combined or "faithfulness" in combined or "hallucination" in combined:
        return "rag"
    if "safety" in combined or "unsafe" in combined:
        return "safety"
    return "conversation"


def _expected(metric: Any, fallback_kind: str) -> str:
    kind = _metric_kind(metric) or fallback_kind
    goal = _scenario_goal(getattr(metric, "_scenario", None))
    expectations = {
        "intent": "The agent should identify the user's requested task and route the conversation to the correct workflow.",
        "persona": "The agent should respond in the required persona and tone while staying professional and helpful.",
        "tone": "The agent should maintain the expected communication style throughout the conversation.",
        "context": "The agent should preserve prior conversation context and use already provided information correctly.",
        "multi_turn": "The agent should maintain continuity across turns and avoid restarting completed parts of the workflow.",
        "conversation_quality": "The conversation should remain coherent, helpful, and easy for the user to continue.",
        "completeness": f"The agent should complete the user's goal{': ' + goal if goal else ''}.",
        "relevancy": "The agent should directly answer the latest user request without switching to an unrelated topic.",
        "response_quality": "The agent should provide a clear, useful response that directly advances the user's request.",
        "response": "The agent response should be clear, useful, accurate, and appropriate for the immediately preceding user request.",
        "workflow": "The agent should complete the requested workflow step and collect or submit the required information.",
        "ui": "The expected UI interaction evidence should be present and successful.",
        "rag": "The response should be grounded in retrieved or reference context with appropriate supporting evidence.",
        "groundedness": "The answer should be supported by the retrieved or reference knowledge.",
        "hallucination": "The agent should avoid unsupported claims that are not present in the available evidence.",
        "safety": "The response should remain safe, compliant, and policy-aligned.",
    }
    return expectations.get(kind, "The metric should satisfy its configured evaluation criteria.")


def _actual_from_metric(metric: Any, failed_turn: dict[str, Any] | None = None) -> Any:
    message = str((failed_turn or {}).get("message") or "").strip()
    if message:
        speaker = str((failed_turn or {}).get("speaker") or "agent").title()
        return f'{speaker} response: "{message}"'
    score = getattr(metric, "score", None)
    reason = str(getattr(metric, "reason", "") or "").strip()
    if reason:
        return reason
    return f"Score = {score}" if score is not None else None


def _failure_copy(metric: Any, failed_turn: dict[str, Any] | None = None) -> dict[str, str]:
    kind = _metric_kind(metric)
    templates = {
        "intent": {
            "summary": "The agent misunderstood the user's intent and moved the conversation into the wrong workflow.",
            "business_impact": "The user may be routed into the wrong process, delaying resolution and increasing the chance of incorrect business actions.",
            "root_cause": "The intent classifier or routing instruction selected a workflow that did not match the user's latest request.",
            "conversation_card": "The conversation below shows the point where the agent interpreted the request incorrectly and started responding as if a different workflow was needed.",
            "recommendation": "Improve intent classification using both the latest message and conversation history before selecting a workflow.",
        },
        "completeness": {
            "summary": "The requested workflow did not reach the expected completed outcome.",
            "business_impact": "The business process remains unresolved, forcing the user or support team to continue the task manually.",
            "root_cause": "The agent stopped or changed direction before all required information and confirmation steps were completed.",
            "conversation_card": "The conversation below shows where the agent failed to carry the user's request through to completion.",
            "recommendation": "Add a completion check that verifies the user's goal is fully satisfied before closing or changing the workflow.",
        },
        "response_quality": {
            "summary": "The agent produced a low-quality response that did not provide useful next-step information.",
            "business_impact": "The user does not receive enough information to continue the workflow with confidence.",
            "root_cause": "The generated response lacked the clarity, specificity, or usefulness required for the user's current request.",
            "conversation_card": "The conversation below highlights the response that failed to provide a practical answer for the user.",
            "recommendation": "Generate responses that directly address the user's latest request with specific, actionable information.",
        },
        "relevancy": {
            "summary": "The response did not answer the user's question and shifted to unrelated information.",
            "business_impact": "The user cannot progress because the answer does not address the immediate problem.",
            "root_cause": "The response generation step focused on a different topic than the user's latest request.",
            "conversation_card": "The conversation below shows the user request and the highlighted answer that failed to respond to it.",
            "recommendation": "Constrain response generation to the latest user question and reject unrelated answer candidates.",
        },
        "context": {
            "summary": "The agent failed to reuse information that was already established earlier in the conversation.",
            "business_impact": "The user must repeat information, increasing frustration and reducing trust in the agent.",
            "root_cause": "The conversation history was not correctly reused when generating the next response.",
            "conversation_card": "The conversation below shows the prior context and the response that failed to apply it.",
            "recommendation": "Reuse conversation memory before asking for additional information or changing workflow state.",
        },
        "multi_turn": {
            "summary": "The agent lost previously established context and unnecessarily restarted the workflow.",
            "business_impact": "The user must repeat information, increasing frustration and reducing confidence in the automation.",
            "root_cause": "The agent forgot the prior turn state and requested or repeated information that was already available.",
            "conversation_card": "The conversation below demonstrates where the agent contradicted earlier context and caused the evaluation failure.",
            "recommendation": "Persist and check multi-turn state before requesting details or restarting the workflow.",
        },
        "conversation_quality": {
            "summary": "The conversation became difficult to follow and did not maintain a helpful support flow.",
            "business_impact": "A confusing conversation increases abandonment risk and may require human support intervention.",
            "root_cause": "The dialogue management strategy did not maintain a coherent, user-centered progression.",
            "conversation_card": "The conversation below shows the exchange where the support flow became unclear or unhelpful.",
            "recommendation": "Improve dialogue policy examples so responses stay coherent, concise, and aligned with the user's path.",
        },
        "workflow": {
            "summary": "The required business workflow step was not completed successfully.",
            "business_impact": "The business process cannot be completed reliably without manual follow-up or rework.",
            "root_cause": "The workflow transitioned to an incorrect state or failed to complete a required action.",
            "conversation_card": "The conversation below shows the workflow step that did not complete as expected.",
            "recommendation": "Validate workflow state before executing the next business action and retry or escalate failed steps.",
        },
        "backend": {
            "summary": "Backend validation found that the system state did not match the expected business outcome.",
            "business_impact": "Incorrect backend behavior may result in inaccurate records, missed tasks, or poor business decisions.",
            "root_cause": "The backend returned data inconsistent with the expected business logic after the conversation completed.",
            "conversation_card": "The evidence below links the conversation outcome to the backend state that failed validation.",
            "recommendation": "Validate backend responses against expected business rules and confirm records are created or updated correctly.",
        },
        "ui": {
            "summary": "The expected user-interface interaction was missing or did not complete successfully.",
            "business_impact": "The user may be blocked from completing the required action in the chatbot experience.",
            "root_cause": "The expected UI element, interaction evidence, or completion signal was not available when needed.",
            "conversation_card": "The conversation below shows where the interaction should have appeared or completed.",
            "recommendation": "Ensure required UI controls are rendered, detectable, and recorded as successful interaction evidence.",
        },
        "safety": {
            "summary": "The response did not satisfy the required safety or policy constraint.",
            "business_impact": "The interaction may create compliance, trust, or user-safety risk.",
            "root_cause": "The safety policy was not applied strongly enough to the generated response.",
            "conversation_card": "The conversation below shows the response that triggered the safety concern.",
            "recommendation": "Strengthen safety instructions and enforce refusal, correction, or escalation behavior for this case.",
        },
        "rag": {
            "summary": "The answer was not sufficiently supported by retrieved knowledge.",
            "business_impact": "The user may receive factually unreliable information because the wrong knowledge was retrieved or applied.",
            "root_cause": "The retrieval or grounding step did not provide evidence that supports the final answer.",
            "conversation_card": "The conversation below shows the answer that was not adequately grounded in supporting knowledge.",
            "recommendation": "Review retrieval quality, source selection, and grounding prompts for the failed answer.",
        },
        "hallucination": {
            "summary": "The agent made an unsupported claim that was not backed by the available evidence.",
            "business_impact": "Unsupported claims can mislead users and create operational or compliance risk.",
            "root_cause": "The generation step introduced information not present in the retrieved context or conversation evidence.",
            "conversation_card": "The conversation below shows the unsupported answer that introduced the hallucination risk.",
            "recommendation": "Require source-backed answers and suppress claims that cannot be traced to available evidence.",
        },
        "groundedness": {
            "summary": "The response was not grounded in the retrieved or reference material.",
            "business_impact": "The user may act on information that is not supported by approved knowledge sources.",
            "root_cause": "The agent did not align the final response with the retrieved evidence.",
            "conversation_card": "The conversation below shows the answer whose support from retrieved evidence was insufficient.",
            "recommendation": "Improve citation and grounding checks before presenting knowledge-based answers.",
        },
        "tone": {
            "summary": "The agent's tone did not match the expected communication style.",
            "business_impact": "A tone mismatch can make the experience feel unprofessional or inconsistent with the brand.",
            "root_cause": "The response generation step did not preserve the configured tone constraints.",
            "conversation_card": "The conversation below shows the response where the tone diverged from expectations.",
            "recommendation": "Tune tone instructions and add examples that reinforce the expected style under failure conditions.",
        },
        "persona": {
            "summary": "The agent drifted from the expected persona or support behavior.",
            "business_impact": "The experience may feel inconsistent, reducing user confidence in the agent.",
            "root_cause": "The persona instruction was not followed consistently during response generation.",
            "conversation_card": "The conversation below shows the response where the agent behavior diverged from the expected persona.",
            "recommendation": "Strengthen persona guidance with positive and negative examples for this scenario.",
        },
        "response": {
            "summary": "The response failed to satisfy the quality requirements for the user's latest request.",
            "business_impact": "The user receives an answer that may not resolve the issue or support the next workflow step.",
            "root_cause": "The agent response did not meet the expected clarity, relevance, or usefulness threshold.",
            "conversation_card": "The conversation below shows the response that failed the response validation criteria.",
            "recommendation": "Revise response instructions so answers are specific, accurate, and aligned with the latest request.",
        },
        "conversation": {
            "summary": "The conversation did not meet the expected quality bar for a production support interaction.",
            "business_impact": "The overall experience may reduce customer trust and increase support escalation.",
            "root_cause": "The conversation flow did not consistently satisfy the configured evaluation criteria.",
            "conversation_card": "The conversation below shows the local exchange that caused the quality failure.",
            "recommendation": "Review the failed exchange and improve prompts or policies for this conversation pattern.",
        },
    }
    selected = dict(templates.get(kind) or templates["conversation"])
    reason = str(getattr(metric, "reason", "") or "").strip()
    if reason and kind in {"intent", "workflow", "backend"}:
        selected["root_cause"] = f'{selected["root_cause"]} Evaluator detail: {reason}'
    return selected


def _backend_failure_copy() -> dict[str, str]:
    return {
        "summary": "Backend validation found that the system state did not match the expected business outcome.",
        "business_impact": "Incorrect backend behavior may result in inaccurate records, missed follow-up, or poor business decisions.",
        "root_cause": "The backend returned data inconsistent with the expected business logic after the conversation completed.",
        "conversation_card": "The backend evidence links the conversation outcome to the system state that failed validation.",
        "recommendation": "Validate backend responses against expected business rules and confirm records are created or updated correctly.",
    }


def _failure_summary(metric: Any, failed_turn: dict[str, Any] | None = None) -> str:
    return _failure_copy(metric, failed_turn)["summary"]


def _root_cause(metric: Any, context: dict[str, Any], fallback_kind: str) -> str:
    return _failure_copy(metric, None)["root_cause"]


def _evidence_explanation(metric: Any, failed_turn: dict[str, Any] | None) -> str:
    return _failure_copy(metric, failed_turn)["conversation_card"]


def _recommendation(metric: Any, fallback_kind: str) -> str:
    return _failure_copy(metric, None)["recommendation"]


def _business_impact(metric: Any) -> str:
    return _failure_copy(metric, None)["business_impact"]


def _failure_message_for_metric(metric: Any, context: dict[str, Any]) -> str:
    turn = _turn_index(metric)
    if turn is None:
        message_id = _metric_message_id(metric)
        if message_id:
            turn = _turn_index_for_message(context.get("conversation") or [], message_id)
    if turn is None:
        return ""
    snippet = _conversation_snippet(context.get("conversation") or [], turn)
    failed = _failed_turn(snippet)
    return str((failed or {}).get("message") or "")


def _scenario_goal(scenario: Any) -> str:
    persona = getattr(scenario, "persona", None)
    return str(getattr(persona, "goal", "") or "")


def _expected_from_metric(metric: Any) -> Any:
    threshold = getattr(metric, "threshold", None)
    return f"Score >= {threshold}" if threshold is not None else None


def _message_value(message: Any, key: str) -> Any:
    if isinstance(message, dict):
        return message.get(key)
    return getattr(message, key, None)


def _message_id(message: Any) -> str | None:
    value = _message_value(message, "conversation_message_id") or _message_value(message, "message_id") or _message_value(message, "id")
    if value:
        return str(value)
    metadata = _message_value(message, "metadata")
    if isinstance(metadata, dict):
        value = metadata.get("conversation_message_id") or metadata.get("message_id") or metadata.get("id")
        if value:
            return str(value)
    return None


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return value


failure_analysis_engine = FailureAnalysisEngine()
