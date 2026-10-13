"""
Evaluation engine — DeepEval metrics scored by a Gemini judge.

Three metrics are wired up here, matching the "shared" dimensions from the
R&D report (Section 3.1):
  1. Goal completion   — G-Eval, custom rubric
  2. Persona/tone adherence — G-Eval, custom rubric
  3. Hallucination / faithfulness — only runs if rag_context was supplied

Add more DeepEval metrics the same way: define a GEval with explicit
evaluation_steps (structured rubrics reduce judge score variance) and
append it to the metrics list in evaluate_transcript().
"""

from __future__ import annotations

import logging
import re
import time
from deepeval.metrics import (
    GEval, 
    HallucinationMetric,
    ConversationalGEval,
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    ContextualRelevancyMetric,
)

logger = logging.getLogger(__name__)
from deepeval.test_case import LLMTestCase, LLMTestCaseParams, ConversationalTestCase
from deepeval.models.base_model import DeepEvalBaseLLM
import google.generativeai as genai

from app.config import settings
from app.schemas import MetricResult, Persona
from typing import Any

import json


METRIC_CONFIG: dict[str, dict[str, Any]] = {
    "Goal Completion": {
        "description": "Did the chatbot complete the user's task?",
        "threshold": 0.8,
    },
    "Persona and Tone Adherence": {
        "description": "Did the chatbot maintain the expected persona, tone, and behavior?",
        "threshold": 0.7,
    },
    "Conversational Quality": {
        "description": "Was the conversation natural, coherent, and helpful?",
        "threshold": 0.75,
    },
    "Context Retention": {
        "description": "Did the chatbot remember previous messages throughout the conversation?",
        "threshold": 0.75,
    },
    "Multi-turn Consistency": {
        "description": "Were responses consistent throughout the conversation?",
        "threshold": 0.75,
    },
    "Intent Understanding": {
        "description": "Did the chatbot correctly understand the user's intent?",
        "threshold": 0.75,
    },
    "Answer Relevancy": {
        "description": "Did the chatbot answer the user's latest question?",
        "threshold": 0.75,
    },
    "Hallucination": {
        "description": "Did the chatbot invent facts or unsupported information?",
        "threshold": 1.0,
    },
    "Completeness": {
        "description": "Did the chatbot provide all required information?",
        "threshold": 0.75,
    },
    "Response Quality": {
        "description": "Was the response clear, accurate, and useful?",
        "threshold": 0.75,
    },
    "Faithfulness": {
        "description": "Was the answer faithful to the retrieved or reference context?",
        "threshold": 0.9,
    },
    "RAG Answer Relevancy": {
        "description": "Was the RAG answer relevant to the user's question?",
        "threshold": 0.8,
    },
    "RAG Hallucination": {
        "description": "Did the RAG answer avoid unsupported information?",
        "threshold": 1.0,
    },
    "Context Precision": {
        "description": "Were the most relevant knowledge chunks retrieved first?",
        "threshold": 0.8,
    },
    "Context Recall": {
        "description": "Were all required knowledge chunks retrieved?",
        "threshold": 0.8,
    },
    "Context Relevancy": {
        "description": "Was the retrieved context relevant to the user's question?",
        "threshold": 0.8,
    },
}

def _parse_and_validate_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    
    try:
        json.loads(text)
    except json.JSONDecodeError:
        sample = text[:200]
        raise RuntimeError(f"Judge model returned invalid JSON: {sample}")
    return text

class GroqJudge(DeepEvalBaseLLM):
    def __init__(self):
        from groq import Groq
        self.client = Groq(api_key=settings.groq_api_key)
        self.model_name = settings.groq_model
        self._fallback = None

    @property
    def fallback(self):
        if self._fallback is None:
            self._fallback = GeminiJudge(
                model_name=settings.gemini_model,
                api_key=settings.gemini_api_key
            )
        return self._fallback

    def load_model(self):
        return self.client

    def generate(self, prompt: str) -> str:
        try:
            if "json" not in prompt.lower():
                prompt = prompt + "\nRespond in JSON format."

            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_completion_tokens=2048,
                reasoning_effort="low",
                include_reasoning=False,
                response_format={"type": "json_object"}
            )
            return _parse_and_validate_json(response.choices[0].message.content)
        except Exception as e:
            logger.warning(f"[Judge Fallback] Groq unavailable or failed → using Gemini ({type(e).__name__}: {e})")
            return self.fallback.generate(prompt)

    async def a_generate(self, prompt: str) -> str:
        try:
            if "json" not in prompt.lower():
                prompt = prompt + "\nRespond in JSON format."

            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_completion_tokens=2048,
                reasoning_effort="low",
                include_reasoning=False,
                response_format={"type": "json_object"}
            )
            return _parse_and_validate_json(response.choices[0].message.content)
        except Exception as e:
            logger.warning(f"[Judge Fallback] Groq unavailable or failed → using Gemini ({type(e).__name__}: {e})")
            return await self.fallback.a_generate(prompt)

    def get_model_name(self) -> str:
        return self.model_name


class GeminiJudge(DeepEvalBaseLLM):
    def __init__(self, model_name: str, api_key: str):
        self.model_name = model_name
        genai.configure(api_key=api_key)
        self.model = self.load_model(model_name)

    def load_model(self, model_name):
        return genai.GenerativeModel(model_name=model_name)

    def generate(self, prompt: str) -> str:
        config = genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.5
        )
        response = self.model.generate_content(prompt, generation_config=config)
        return _parse_and_validate_json(response.text)

    async def a_generate(self, prompt: str) -> str:
        config = genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.5
        )
        response = await self.model.generate_content_async(prompt, generation_config=config)
        return _parse_and_validate_json(response.text)

    def get_model_name(self) -> str:
        return self.model_name

_judge = None


def get_judge() -> GroqJudge:
    global _judge
    if _judge is None:
        _judge = GroqJudge()
    return _judge


def _transcript_to_text(transcript: list[Any]) -> str:
    lines = []
    for t in transcript:
        speaker = "User" if _message_value(t, "role") == "simulated_user" else "Agent"
        lines.append(f"{speaker}: {_message_value(t, 'content')}")
    return "\n".join(lines)


def _message_value(message: Any, key: str) -> Any:
    if isinstance(message, dict):
        return message.get(key)
    return getattr(message, key, None)


def _metric_config_name(name: str, category: str | None = None) -> str:
    if category == "rag" and name in {"Answer Relevancy", "Hallucination"}:
        return f"RAG {name}"
    return name


def _metric_description(name: str, category: str | None = None) -> str:
    return METRIC_CONFIG.get(_metric_config_name(name, category), {}).get("description", "")


def _metric_threshold(name: str, category: str | None = None) -> float:
    return float(METRIC_CONFIG.get(_metric_config_name(name, category), {}).get("threshold", 0.7))


def _build_metrics(persona: Persona, rag_context: list[str] | None) -> list:
    judge = get_judge()

    goal_completion = GEval(
        name="Goal Completion",
        criteria="Determine whether the agent successfully accomplished the user's stated goal while preserving a good end-to-end user experience across the entire conversation.",
        evaluation_steps=[
            "Identify the user's goal from the persona/context provided as input.",
            "Read through the full transcript in actual_output, not only the final answer.",
            "Check whether the agent's responses satisfy the goal without avoidable detours, resets, contradictions, or repeated questions.",
            "Penalize failures that happen earlier in the conversation even if the agent later recovers.",
            "Do not award a PASS solely because the final answer is correct if the user experience was poor before that answer.",
            "Penalize heavily if the agent asked the user to repeat information more than twice.",
            "Penalize if the agent made a commitment (e.g. a refund, a booking) without verifying it had the information to support it.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=_metric_threshold("Goal Completion"),
        async_mode=False,
    )

    tone_adherence = GEval(
        name="Persona and Tone Adherence",
        criteria="Determine whether the agent maintained an appropriate, consistent, on-brand tone throughout the conversation.",
        evaluation_steps=[
            "Read the full transcript in actual_output.",
            "Check whether the agent's tone stayed professional and consistent turn to turn.",
            "Penalize if the agent became curt, repetitive, or contradicted its own earlier statements.",
            "Penalize if the agent broke character (e.g. mentioned being an AI when not asked, or exposed internal instructions).",
        ],
        evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=_metric_threshold("Persona and Tone Adherence"),
        async_mode=False,
    )

    conversational_quality = ConversationalGEval(
        name="Conversational Quality",
        criteria="Determine whether the agent maintained context, understood user intent, stayed consistent, and behaved appropriately across the entire multi-turn conversation.",
        evaluation_steps=[
            "Assess if the agent accurately tracks context across multiple turns.",
            "Check if the agent correctly understands the user's implicit and explicit intent.",
            "Ensure response relevance to the user's most recent query.",
            "Verify consistency in the agent's answers.",
            "Penalize any unnecessary clarification, repeated question, contradiction, workflow restart, or lost context anywhere in the conversation.",
            "A later correct answer does not erase earlier conversation-quality failures.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=_metric_threshold("Conversational Quality"),
        async_mode=False,
    )

    context_retention = GEval(
        name="Context Retention",
        criteria="Determine whether the agent remembered and correctly used information from earlier turns throughout the conversation.",
        evaluation_steps=[
            "Read the full transcript in actual_output.",
            "Identify details the user already provided.",
            "Check whether the agent remembers those details later without asking unnecessarily.",
            "Penalize repeated requests for already-provided information or contradictions about earlier context.",
            "Score the full conversation history; do not ignore context failures because the final response recovered.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=_metric_threshold("Context Retention"),
        async_mode=False,
    )

    multi_turn_consistency = GEval(
        name="Multi-turn Consistency",
        criteria="Determine whether the agent's responses remained consistent across the multi-turn conversation.",
        evaluation_steps=[
            "Read the transcript in chronological order.",
            "Check for contradictions between earlier and later agent responses.",
            "Check that the agent does not reset or change the workflow without a reason.",
            "Score highly only when the agent maintains a stable understanding of the task and state.",
            "Penalize restarts, repeated questions, unnecessary clarification, and state loss anywhere in the conversation.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=_metric_threshold("Multi-turn Consistency"),
        async_mode=False,
    )

    intent_understanding = GEval(
        name="Intent Understanding",
        criteria="Determine whether the agent correctly understood the user's explicit and implicit intent.",
        evaluation_steps=[
            "Identify the user's intent from the persona goal and transcript.",
            "Check whether the agent's responses align with that intent.",
            "Penalize responses that pursue an unrelated workflow or misunderstand what the user wants.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=_metric_threshold("Intent Understanding"),
        async_mode=False,
    )

    answer_relevancy = GEval(
        name="Answer Relevancy",
        criteria="Determine whether the agent answered the user's latest question or request in each turn without relying on RAG context.",
        evaluation_steps=[
            "Review each user message and the immediately following agent response.",
            "Check whether the agent response directly addresses the latest user question or request.",
            "Penalize generic, off-topic, stale, or workflow-reset responses.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=_metric_threshold("Answer Relevancy"),
        async_mode=False,
    )

    hallucination = GEval(
        name="Hallucination",
        criteria="Determine whether the agent invented facts, commitments, policies, IDs, bookings, prices, or outcomes unsupported by the conversation.",
        evaluation_steps=[
            "Use only the persona goal and transcript as evidence.",
            "Identify factual claims or commitments made by the agent.",
            "Penalize unsupported claims, fabricated details, or commitments not justified by collected information.",
            "Score 1.0 when no unsupported information is detected.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=_metric_threshold("Hallucination"),
        async_mode=False,
    )

    completeness = GEval(
        name="Completeness",
        criteria="Determine whether the agent provided all required information or collected all information needed to complete the task.",
        evaluation_steps=[
            "Identify the required information from the user's goal and conversation.",
            "Check whether the agent collected or provided all necessary pieces.",
            "Penalize missing required fields, incomplete next steps, or unresolved task state.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=_metric_threshold("Completeness"),
        async_mode=False,
    )

    response_quality = GEval(
        name="Response Quality",
        criteria="Determine whether the agent's responses were clear, accurate, concise, and useful.",
        evaluation_steps=[
            "Assess clarity and usefulness of the agent responses.",
            "Check for confusing wording, unnecessary repetition, or low-value replies.",
            "Reward accurate, concise, actionable responses that help the user progress.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=_metric_threshold("Response Quality"),
        async_mode=False,
    )

    metrics = [
        goal_completion,
        tone_adherence,
        conversational_quality,
        context_retention,
        multi_turn_consistency,
        intent_understanding,
        answer_relevancy,
        hallucination,
        completeness,
        response_quality,
    ]

    if rag_context:
        metrics.extend(_build_rag_metrics())

    return metrics


def _build_rag_metrics() -> list:
    judge = get_judge()
    return [
        HallucinationMetric(threshold=_metric_threshold("Hallucination", "rag"), model=judge, async_mode=False),
        AnswerRelevancyMetric(threshold=_metric_threshold("Answer Relevancy", "rag"), model=judge, async_mode=False),
        FaithfulnessMetric(threshold=_metric_threshold("Faithfulness", "rag"), model=judge, async_mode=False),
        ContextualPrecisionMetric(threshold=_metric_threshold("Context Precision"), model=judge, async_mode=False),
        ContextualRecallMetric(threshold=_metric_threshold("Context Recall"), model=judge, async_mode=False),
        ContextualRelevancyMetric(threshold=_metric_threshold("Context Relevancy"), model=judge, async_mode=False),
    ]

def _metric_name(metric) -> str:
    if isinstance(metric, HallucinationMetric):
        return "Hallucination"
    if isinstance(metric, AnswerRelevancyMetric):
        return "Answer Relevancy"
    if isinstance(metric, FaithfulnessMetric):
        return "Faithfulness"
    if isinstance(metric, ContextualPrecisionMetric):
        return "Context Precision"
    if isinstance(metric, ContextualRecallMetric):
        return "Context Recall"
    if isinstance(metric, ContextualRelevancyMetric):
        return "Context Relevancy"
    if hasattr(metric, "name"):
        return metric.name
        
    name = type(metric).__name__
    if name.endswith("Metric"):
        name = name[:-6]
    import re
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', name)


def _is_rag_metric(metric: Any) -> bool:
    return isinstance(metric, (
        HallucinationMetric,
        AnswerRelevancyMetric,
        FaithfulnessMetric,
        ContextualPrecisionMetric,
        ContextualRecallMetric,
        ContextualRelevancyMetric,
    ))


def evaluate_transcript(
    persona: Persona,
    transcript: list[Any],
    rag_context: list[str] | None = None,
    rag_evidence_by_turn: list[dict[str, Any]] | None = None,
) -> list[MetricResult]:
    start = time.perf_counter()
    try:
        transcript_text = _transcript_to_text(transcript)

        # Build standard LLM test case
        test_case = LLMTestCase(
            input=f"User goal: {persona.goal}\nUser persona: {persona.name} ({persona.tone})",
            actual_output=transcript_text,
            context=rag_context if rag_context else ["No specific context provided."],
            retrieval_context=rag_context,
            expected_output=None,
        )

        # Build ConversationalTestCase for ConversationalGEval
        turns = []
        for t in transcript:
            turns.append(LLMTestCase(
                input=_message_value(t, "content") if _message_value(t, "role") == "simulated_user" else "",
                actual_output=_message_value(t, "content") if _message_value(t, "role") == "agent" else ""
            ))
        conversational_test_case = ConversationalTestCase(turns=turns)

        metrics = _build_metrics(persona, rag_context)
        results: list[MetricResult] = []

        logger.info("[EVALUATION START]")
        
        for metric in metrics:
            metric_start = time.perf_counter()
            metric_name_str = _metric_name(metric)
            logger.info(f"[EVAL METRIC START] {metric_name_str}")
            
            try:
                if isinstance(metric, ConversationalGEval):
                    metric.measure(conversational_test_case)
                else:
                    metric.measure(test_case)
                    
                metric_elapsed = time.perf_counter() - metric_start
                logger.info(f"[EVAL METRIC END] {metric_name_str} duration={metric_elapsed:.3f}s")
                
                raw_score = float(metric.score)
                
                # Explicit normalization
                if isinstance(metric, HallucinationMetric):
                    normalized_score = 1.0 - raw_score
                else:
                    normalized_score = raw_score
                    
                results.append(
                    MetricResult(
                        name=metric_name_str,
                        description=_metric_description(metric_name_str, "rag" if _is_rag_metric(metric) else "base"),
                        score=round(normalized_score, 3),
                        reason=metric.reason or "",
                        passed=bool(metric.success),
                        threshold=_metric_threshold(metric_name_str, "rag" if _is_rag_metric(metric) else "base"),
                        category="rag" if _is_rag_metric(metric) else "base",
                        evidence_source="reference_context" if rag_context and _is_rag_metric(metric) else None,
                        **_metric_reference(transcript, metric_name_str, metric_reason=metric.reason or ""),
                    )
                )
            except Exception as e:
                metric_elapsed = time.perf_counter() - metric_start
                logger.error(f"[EVAL METRIC FAILED] {metric_name_str} duration={metric_elapsed:.3f}s error={type(e).__name__}: {e}")
                results.append(
                    MetricResult(
                        name=metric_name_str,
                        description=_metric_description(metric_name_str, "rag" if _is_rag_metric(metric) else "base"),
                        score=0.0,
                        reason=f"Metric failed to evaluate: {type(e).__name__} - {str(e)}",
                        passed=False,
                        threshold=_metric_threshold(metric_name_str, "rag" if _is_rag_metric(metric) else "base"),
                        category="rag" if _is_rag_metric(metric) else "base",
                        evidence_source="reference_context" if rag_context and _is_rag_metric(metric) else None,
                        **_metric_reference(
                            transcript,
                            metric_name_str,
                            metric_reason=f"Metric failed to evaluate: {type(e).__name__} - {str(e)}",
                        ),
                    )
                )

        if rag_evidence_by_turn:
            for index, turn_evidence in enumerate(rag_evidence_by_turn, start=1):
                contexts = [
                    ctx for ctx in (turn_evidence.get("contexts") or [])
                    if isinstance(ctx, str) and ctx.strip()
                ]
                if not contexts:
                    continue

                rag_test_case = LLMTestCase(
                    input=str(turn_evidence.get("input") or ""),
                    actual_output=str(turn_evidence.get("actual_output") or ""),
                    context=contexts,
                    retrieval_context=contexts,
                )

                for metric in _build_rag_metrics():
                    metric_start = time.perf_counter()
                    metric_name_str = _metric_name(metric)
                    result_name = metric_name_str if len(rag_evidence_by_turn) == 1 else f"{metric_name_str} (Turn {index})"
                    logger.info(f"[EVAL METRIC START] {result_name}")

                    try:
                        metric.measure(rag_test_case)

                        metric_elapsed = time.perf_counter() - metric_start
                        logger.info(f"[EVAL METRIC END] {result_name} duration={metric_elapsed:.3f}s")

                        raw_score = float(metric.score)
                        normalized_score = 1.0 - raw_score if isinstance(metric, HallucinationMetric) else raw_score

                        results.append(
                            MetricResult(
                                name=result_name,
                                description=_metric_description(metric_name_str, "rag"),
                                score=round(normalized_score, 3),
                                reason=metric.reason or "",
                                passed=bool(metric.success),
                                threshold=_metric_threshold(metric_name_str, "rag"),
                                category="rag",
                                evidence_source=str(turn_evidence.get("source") or "agent_retrieval"),
                                **_metric_reference(
                                    transcript,
                                    result_name,
                                    explicit_turn_index=turn_evidence.get("turn_index"),
                                    explicit_message_id=turn_evidence.get("conversation_message_id"),
                                ),
                            )
                        )
                    except Exception as e:
                        metric_elapsed = time.perf_counter() - metric_start
                        logger.error(f"[EVAL METRIC FAILED] {result_name} duration={metric_elapsed:.3f}s error={type(e).__name__}: {e}")
                        results.append(
                            MetricResult(
                                name=result_name,
                                description=_metric_description(metric_name_str, "rag"),
                                score=0.0,
                                reason=f"Metric failed to evaluate: {type(e).__name__} - {str(e)}",
                                passed=False,
                                threshold=_metric_threshold(metric_name_str, "rag"),
                                category="rag",
                                evidence_source=str(turn_evidence.get("source") or "agent_retrieval"),
                                **_metric_reference(
                                    transcript,
                                    result_name,
                                    explicit_turn_index=turn_evidence.get("turn_index"),
                                    explicit_message_id=turn_evidence.get("conversation_message_id"),
                                ),
                            )
                        )

        _apply_conversation_experience_penalties(results, transcript)
        elapsed = time.perf_counter() - start
        logger.info(f"[EVALUATION END] total_duration={elapsed:.3f}s")
        return results
    except Exception as e:
        elapsed = time.perf_counter() - start
        logger.error(f"[STAGE: DeepEval/Gemini Evaluation FAILED] elapsed={elapsed:.3f}s exception={type(e).__name__}: {e}")
        raise


def _metric_reference(
    transcript: list[Any],
    metric_name: str,
    *,
    metric_reason: str | None = None,
    explicit_turn_index: Any = None,
    explicit_message_id: Any = None,
) -> dict[str, Any]:
    if isinstance(explicit_turn_index, int):
        return {
            "turn_index": explicit_turn_index,
            "conversation_message_id": str(explicit_message_id or _message_identity(_message_at_turn(transcript, explicit_turn_index), explicit_turn_index)),
        }

    target = (
        _message_referenced_by_metric_reason(transcript, metric_name, metric_reason)
        or _message_referenced_by_metric_type(transcript, metric_name)
        or _last_agent_message(transcript)
        or (transcript[-1] if transcript else None)
    )
    if target is None:
        return {}
    turn_index = _message_turn_index(target, max(0, len(transcript) - 1))
    return {
        "turn_index": turn_index,
        "conversation_message_id": _message_identity(target, turn_index),
    }


def _apply_conversation_experience_penalties(results: list[MetricResult], transcript: list[Any]) -> None:
    findings = _conversation_experience_findings(transcript)
    if not findings:
        return
    affected = {
        "goal completion",
        "conversational quality",
        "context retention",
        "multi-turn consistency",
        "intent understanding",
        "answer relevancy",
        "completeness",
        "response quality",
        "persona and tone adherence",
    }
    penalty_text = "Full-conversation penalty: " + "; ".join(findings)
    severe = any(any(word in finding.lower() for word in ("restart", "contradict", "already provided")) for finding in findings)
    cap = 0.55 if severe else 0.65
    for result in results:
        if str(result.category or "").lower() == "rag":
            continue
        if str(result.name or "").lower() not in affected:
            continue
        if result.score > cap:
            result.score = round(cap, 3)
        result.passed = bool(result.score >= result.threshold)
        result.reason = f"{result.reason} {penalty_text}".strip() if result.reason else penalty_text


def _conversation_experience_findings(transcript: list[Any]) -> list[str]:
    agent_messages = [
        (index, str(_message_value(message, "content") or ""))
        for index, message in enumerate(transcript or [])
        if _message_value(message, "role") == "agent"
    ]
    findings: list[str] = []
    findings.extend(_repeated_question_findings(agent_messages))
    findings.extend(_restart_findings(agent_messages))
    findings.extend(_context_loss_findings(transcript))
    findings.extend(_contradiction_findings(agent_messages))
    return _unique_findings(findings)


def _repeated_question_findings(agent_messages: list[tuple[int, str]]) -> list[str]:
    seen: dict[str, int] = {}
    findings: list[str] = []
    for turn, text in agent_messages:
        question = _normalized_question(text)
        if not question:
            continue
        previous = seen.get(question)
        if previous is not None:
            findings.append(f"Agent repeated the same question at turns {previous} and {turn}.")
        else:
            seen[question] = turn
    return findings


def _restart_findings(agent_messages: list[tuple[int, str]]) -> list[str]:
    patterns = (
        "start over",
        "start again",
        "restart",
        "begin again",
        "from the beginning",
        "let's begin again",
        "let us begin again",
    )
    return [
        f"Agent restarted or reset the workflow at turn {turn}."
        for turn, text in agent_messages
        if any(pattern in text.lower() for pattern in patterns)
    ]


def _context_loss_findings(transcript: list[Any]) -> list[str]:
    provided = {
        "phone": False,
        "date": False,
        "time": False,
        "email": False,
        "name": False,
    }
    findings: list[str] = []
    for index, message in enumerate(transcript or []):
        role = _message_value(message, "role")
        text = str(_message_value(message, "content") or "")
        lowered = text.lower()
        if role in {"simulated_user", "user"}:
            provided["phone"] = provided["phone"] or bool(re.search(r"\b\d{7,15}\b", text))
            provided["date"] = provided["date"] or bool(re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d{4}-\d{2}-\d{2})", lowered))
            provided["time"] = provided["time"] or bool(re.search(r"\b\d{1,2}:\d{2}\b|\b\d{1,2}\s?(?:am|pm)\b", lowered))
            provided["email"] = provided["email"] or bool(re.search(r"[\w.+-]+@[\w.-]+\.\w+", text))
            provided["name"] = provided["name"] or _looks_like_name_answer(text)
            continue
        if role != "agent":
            continue
        requested = []
        if provided["phone"] and any(phrase in lowered for phrase in ("phone number", "contact number", "mobile number")):
            requested.append("phone number")
        if provided["date"] and any(phrase in lowered for phrase in ("preferred date", "what date", "which date", "appointment date")):
            requested.append("date")
        if provided["time"] and any(phrase in lowered for phrase in ("preferred time", "what time", "which time", "appointment time")):
            requested.append("time")
        if provided["email"] and "email" in lowered:
            requested.append("email")
        if provided["name"] and any(phrase in lowered for phrase in ("your name", "may i have your name", "can i have your name")):
            requested.append("name")
        if requested:
            findings.append(f"Agent asked for already provided {', '.join(requested)} at turn {index}.")
        if _asks_unnecessary_clarification(lowered) and _previous_user_context_length(transcript, index) >= 40:
            findings.append(f"Agent asked for unnecessary clarification despite existing context at turn {index}.")
    return findings


def _contradiction_findings(agent_messages: list[tuple[int, str]]) -> list[str]:
    findings: list[str] = []
    prior_positive: int | None = None
    prior_negative: int | None = None
    for turn, text in agent_messages:
        lowered = text.lower()
        positive = any(phrase in lowered for phrase in ("confirmed", "completed", "created", "booked", "submitted", "found"))
        negative = any(phrase in lowered for phrase in ("cannot", "can't", "unable", "not found", "no matching", "not available"))
        if positive and prior_negative is not None:
            findings.append(f"Agent contradicted an earlier negative outcome between turns {prior_negative} and {turn}.")
        if negative and prior_positive is not None:
            findings.append(f"Agent contradicted an earlier successful outcome between turns {prior_positive} and {turn}.")
        if positive:
            prior_positive = turn
        if negative:
            prior_negative = turn
    return findings


def _normalized_question(text: str) -> str:
    question = " ".join(part.strip() for part in re.split(r"[.!]", text) if "?" in part or _looks_like_question(part))
    question = re.sub(r"[^a-z0-9 ]+", "", question.lower())
    question = re.sub(r"\s+", " ", question).strip()
    return question if len(question) >= 12 else ""


def _looks_like_question(text: str) -> bool:
    lowered = str(text or "").lower().strip()
    return lowered.startswith(("can you", "could you", "please provide", "may i", "what ", "which ", "who ", "where ", "when ", "do you", "did you"))


def _looks_like_name_answer(text: str) -> bool:
    stripped = str(text or "").strip()
    if len(stripped.split()) not in {2, 3}:
        return False
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z .'-]+", stripped))


def _asks_unnecessary_clarification(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in (
            "need more detail",
            "need a bit more detail",
            "please clarify",
            "which property",
            "which project",
            "what property",
            "what project",
            "can you provide more information",
            "could you provide more information",
        )
    )


def _previous_user_context_length(transcript: list[Any], index: int) -> int:
    return sum(
        len(str(_message_value(message, "content") or ""))
        for message in transcript[:index]
        if _message_value(message, "role") in {"simulated_user", "user"}
    )


def _unique_findings(findings: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for finding in findings:
        if finding in seen:
            continue
        seen.add(finding)
        unique.append(finding)
    return unique[:5]


def _message_referenced_by_metric_reason(transcript: list[Any], metric_name: str, metric_reason: str | None) -> Any:
    normalized_metric = _normalize_match_text(f"{metric_name} {metric_reason or ''}")
    candidates = _messages_for_metric_match(transcript, metric_name)
    best = None
    best_score = 0
    for message in candidates:
        content = _normalize_match_text(_message_value(message, "content"))
        if not content:
            continue
        score = 0
        for fragment in _meaningful_fragments(normalized_metric):
            if fragment in content:
                score += len(fragment)
        if score > best_score:
            best = message
            best_score = score
    return best if best_score >= 12 else None


def _messages_for_metric_match(transcript: list[Any], metric_name: str) -> list[Any]:
    kind = _metric_reference_kind(metric_name)
    agent_first_kinds = {
        "intent",
        "persona",
        "context",
        "completeness",
        "relevancy",
        "response",
        "safety",
    }
    if kind in agent_first_kinds:
        agent_messages = [message for message in transcript or [] if _message_value(message, "role") == "agent"]
        return agent_messages or list(transcript or [])
    return list(transcript or [])


def _metric_reference_kind(metric_name: str) -> str:
    name = str(metric_name or "").lower()
    if "intent" in name:
        return "intent"
    if "persona" in name or "tone" in name:
        return "persona"
    if "context" in name or "memory" in name or "consistency" in name:
        return "context"
    if "complete" in name or "completion" in name or "goal" in name:
        return "completeness"
    if "relevancy" in name or "relevance" in name or "answer" in name:
        return "relevancy"
    if "response" in name or "quality" in name:
        return "response"
    if "safety" in name:
        return "safety"
    return "conversation"


def _message_referenced_by_metric_type(transcript: list[Any], metric_name: str) -> Any:
    kind = _metric_reference_kind(metric_name)
    agent_messages = [message for message in transcript or [] if _message_value(message, "role") == "agent"]
    user_messages = [message for message in transcript or [] if _message_value(message, "role") in {"simulated_user", "user"}]
    if not transcript:
        return None
    if kind == "intent":
        return agent_messages[0] if agent_messages else transcript[0]
    if kind == "persona":
        return _longest_message(agent_messages) or (agent_messages[-1] if agent_messages else None)
    if kind == "context":
        return agent_messages[-1] if agent_messages else None
    if kind in {"relevancy", "response"}:
        return agent_messages[-1] if agent_messages else None
    if kind == "completeness":
        return agent_messages[-1] if agent_messages else (user_messages[-1] if user_messages else transcript[-1])
    if kind == "safety":
        return agent_messages[-1] if agent_messages else None
    return None


def _longest_message(messages: list[Any]) -> Any:
    if not messages:
        return None
    return max(messages, key=lambda item: len(str(_message_value(item, "content") or "")))


def _meaningful_fragments(text: str) -> list[str]:
    quoted = re.findall(r'"([^"]{8,})"|\'([^\']{8,})\'', text)
    fragments = [a or b for a, b in quoted if (a or b)]
    sentences = re.split(r"[.!?]\s+", text)
    fragments.extend(sentence.strip() for sentence in sentences if len(sentence.strip()) >= 24)
    return fragments[:8]


def _normalize_match_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def _message_at_turn(transcript: list[Any], turn_index: int) -> Any:
    for index, message in enumerate(transcript):
        if _message_turn_index(message, index) == turn_index:
            return message
    return None


def _last_agent_message(transcript: list[Any]) -> Any:
    for message in reversed(transcript or []):
        if _message_value(message, "role") == "agent":
            return message
    return None


def _message_turn_index(message: Any, fallback: int) -> int:
    value = _message_value(message, "turn_index")
    return value if isinstance(value, int) else fallback


def _message_identity(message: Any, turn_index: int) -> str:
    if message is None:
        return f"ef-turn-{turn_index}"
    existing = (
        _message_value(message, "conversation_message_id")
        or _message_value(message, "message_id")
        or _message_value(message, "id")
    )
    if existing:
        return str(existing)
    metadata = _message_value(message, "metadata")
    if isinstance(metadata, dict):
        existing = metadata.get("conversation_message_id") or metadata.get("message_id") or metadata.get("id")
        if existing:
            return str(existing)
    return f"ef-turn-{turn_index}"
