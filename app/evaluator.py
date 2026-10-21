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
from contextvars import ContextVar, Token
from dataclasses import dataclass
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
from app.evaluation_evidence import (
    assess_factual_claims,
    classify_technical_errors,
    detect_structured_contradictions,
    validate_numerical_evidence,
)
from typing import Any

import json


_judge_invocations: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "judge_invocations", default=None
)


def _record_judge_invocation(**details: Any) -> None:
    capture = _judge_invocations.get()
    if capture is not None:
        capture.append(details)


def _start_judge_capture() -> Token:
    return _judge_invocations.set([])


def _finish_judge_capture(token: Token) -> list[dict[str, Any]]:
    captured = list(_judge_invocations.get() or [])
    _judge_invocations.reset(token)
    return captured


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
            result = _parse_and_validate_json(response.choices[0].message.content)
            _record_judge_invocation(
                provider="groq", model=self.model_name, fallback_used=False,
                temperature=0.5, reasoning_effort="low", status="success",
            )
            return result
        except Exception as e:
            logger.warning(f"[Judge Fallback] Groq unavailable or failed → using Gemini ({type(e).__name__}: {e})")
            try:
                result = self.fallback.generate(prompt)
                _record_judge_invocation(
                    provider="gemini", model=self.fallback.get_model_name(), fallback_used=True,
                    primary_provider="groq", primary_model=self.model_name,
                    primary_error=type(e).__name__, temperature=0.5, status="success",
                )
                return result
            except Exception as fallback_error:
                _record_judge_invocation(
                    provider="gemini", model=self.fallback.get_model_name(), fallback_used=True,
                    primary_provider="groq", primary_model=self.model_name,
                    primary_error=type(e).__name__, error=type(fallback_error).__name__,
                    temperature=0.5, status="error",
                )
                raise

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
            result = _parse_and_validate_json(response.choices[0].message.content)
            _record_judge_invocation(
                provider="groq", model=self.model_name, fallback_used=False,
                temperature=0.5, reasoning_effort="low", status="success",
            )
            return result
        except Exception as e:
            logger.warning(f"[Judge Fallback] Groq unavailable or failed → using Gemini ({type(e).__name__}: {e})")
            try:
                result = await self.fallback.a_generate(prompt)
                _record_judge_invocation(
                    provider="gemini", model=self.fallback.get_model_name(), fallback_used=True,
                    primary_provider="groq", primary_model=self.model_name,
                    primary_error=type(e).__name__, temperature=0.5, status="success",
                )
                return result
            except Exception as fallback_error:
                _record_judge_invocation(
                    provider="gemini", model=self.fallback.get_model_name(), fallback_used=True,
                    primary_provider="groq", primary_model=self.model_name,
                    primary_error=type(e).__name__, error=type(fallback_error).__name__,
                    temperature=0.5, status="error",
                )
                raise

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
        speaker = "User" if _message_value(t, "role") in {"simulated_user", "user"} else "Agent"
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


def _agent_expectation_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return "; ".join(
            f"{key}: {item}" for key, item in value.items()
            if item not in (None, "", [], {})
        )
    if hasattr(value, "model_dump"):
        return _agent_expectation_text(value.model_dump(exclude_none=True))
    return str(value).strip()


def _full_conversation_input(persona: Persona, expected_agent_persona: Any) -> str:
    agent_expectations = _agent_expectation_text(expected_agent_persona)
    return "\n".join([
        f"Original simulated-user goal: {persona.goal}",
        f"Simulated-user profile (not agent requirements): name={persona.name}; tone={persona.tone}",
        (
            f"Expected-agent behavior: {agent_expectations}"
            if agent_expectations else
            "Expected-agent behavior: No explicit agent persona is configured. Apply only provider-neutral professional, clear, respectful, and consistent communication criteria."
        ),
    ])


def _tone_evaluation_input(expected_agent_persona: Any) -> str:
    agent_expectations = _agent_expectation_text(expected_agent_persona)
    if agent_expectations:
        return f"Expected-agent communication behavior: {agent_expectations}"
    return (
        "No explicit agent persona is configured. Evaluate only whether the agent's "
        "communication is professional, clear, respectful, and stylistically consistent."
    )


def _build_metrics(
    persona: Persona,
    rag_context: list[str] | None,
    expected_agent_persona: Any = None,
) -> list:
    judge = get_judge()

    goal_completion = GEval(
        name="Goal Completion",
        criteria="Determine whether the agent accomplished the original user goal across the full conversation. Score later follow-up answer quality in its own metrics.",
        evaluation_steps=[
            "Identify the user's goal from the persona/context provided as input.",
            "Read through the full transcript in actual_output, not only the final answer.",
            "Check whether the original goal was actually fulfilled, using all relevant turns and any later reversal of that outcome.",
            "Do not treat a later unrelated correct answer as proof that the original goal was completed.",
            "Assess follow-up relevance, repeated questions, and conversation experience in their dedicated metrics.",
            "Treat an explicit statement that the requested action was completed as task completion unless the conversation or independent evidence contradicts it.",
            "Do not invent extra confirmation, verification, or workflow requirements that are absent from the user's goal.",
            "Penalize if the agent made a commitment (e.g. a refund, a booking) without verifying it had the information to support it.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=_metric_threshold("Goal Completion"),
        async_mode=False,
    )

    has_agent_expectations = bool(_agent_expectation_text(expected_agent_persona))
    tone_adherence = GEval(
        name="Persona and Tone Adherence",
        criteria=(
            "Determine only whether the agent maintained the explicitly configured agent persona and communication style throughout the conversation."
            if has_agent_expectations else
            "Determine only whether the agent communicated professionally, clearly, respectfully, and consistently. No agent persona is configured, so do not invent one."
        ) + " Do not score task completion, answer relevance, factual correctness, or backend execution in this metric.",
        evaluation_steps=[
            "Use only explicit expected-agent behavior from Input; the simulated user's name, role, and tone are not agent requirements.",
            "Read the full transcript in actual_output.",
            "Check only whether the agent's communication style matches explicit agent requirements, or provider-neutral professional communication criteria when none are configured.",
            "Do not reduce the tone score merely because an answer is irrelevant, incomplete, factually wrong, or unsuccessful.",
            "A polite, reassuring, or professional response can pass this metric even when it performs the wrong task.",
            "A rude, hostile, dismissive, or persona-breaking response must fail even when the task succeeds.",
            "Penalize if the agent broke character (e.g. mentioned being an AI when not asked, or exposed internal instructions).",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
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
            "Check whether the agent remembers details that remain relevant to the active task without asking unnecessarily.",
            "Do not penalize a clarification when essential information is genuinely missing, the user changed the requirement, or the earlier detail belongs to another task.",
            "Do not treat failure to complete an earlier task as forgotten context when the agent explicitly acknowledged that task or limitation.",
            "When the user intentionally starts an independent topic, judge retention only on prior details that remain relevant to the new topic.",
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
            "Check that the agent does not reset or change the established workflow state without a reason.",
            "Score highly only when the agent maintains a stable understanding of the task and state.",
            "Penalize contradictions and unjustified workflow-state resets. Leave repetition, clarification quality, and forgotten user facts to their dedicated metrics unless they also create an actual inconsistency.",
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
            "Distinguish misunderstanding the request from correctly understanding it but failing to execute it.",
            "Treat a clarification as correct when the request is genuinely ambiguous; do not infer intent failure from outcome failure alone.",
            "Penalize responses that pursue an unrelated workflow or misunderstand what the user wants.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.CONTEXT],
        model=judge,
        threshold=_metric_threshold("Intent Understanding"),
        async_mode=False,
    )

    answer_relevancy = GEval(
        name="Answer Relevancy",
        criteria="Determine whether the agent answered the user's latest question or request in each turn without relying on RAG context.",
        evaluation_steps=[
            "Review each user message and the immediately following agent response.",
            "Check whether the agent response directly addresses the latest user question, active subtask, and relevant prior context.",
            "Treat a necessary clarification as relevant, and do not use later unrelated messages to judge an earlier exchange.",
            "Judge topical responsiveness, not completeness or business-action success: an on-topic partial answer may be relevant but incomplete.",
            "A transparent inability or limitation directly about the requested action is relevant even if the action cannot be completed.",
            "Penalize generic, off-topic, stale, or workflow-reset responses.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.CONTEXT],
        model=judge,
        threshold=_metric_threshold("Answer Relevancy"),
        async_mode=False,
    )

    hallucination = GEval(
        name="Hallucination",
        criteria="Determine the agent's factual reliability: a higher score means no established fabrication or contradiction, and a lower score means the available evidence proves a factual error or invented claim.",
        evaluation_steps=[
            "Use only the persona goal and transcript as evidence.",
            "Identify factual claims or commitments made by the agent.",
            "Compare claims against facts explicitly available in the conversation; check arithmetic when the inputs and claimed result are present.",
            "Penalize a contradiction, calculation error, or invented transaction outcome only when the available evidence establishes it.",
            "Missing backend or retrieval evidence alone does not establish hallucination. Do not infer that an unverified claim is false.",
            "Assign the highest score when no contradiction or fabrication is established by available evidence, and a low score only when available evidence establishes one.",
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
            "Identify the information required by the current user request using Input and relevant prior Context.",
            "Check whether the agent collected or provided all necessary pieces.",
            "Treat a necessary clarification, supported limitation, or appropriate refusal as complete for that conversational step when it directly addresses the request.",
            "Do not score factual correctness, tone, or eventual business-action success in this metric.",
            "Penalize missing required fields, incomplete next steps, or unresolved task state.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.CONTEXT],
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
    expected_agent_persona: Any = None,
) -> list[MetricResult]:
    start = time.perf_counter()
    try:
        transcript_text = _transcript_to_text(transcript)

        # Build standard LLM test case
        test_case = LLMTestCase(
            input=_full_conversation_input(persona, expected_agent_persona),
            actual_output=transcript_text,
            context=rag_context if rag_context else ["No specific context provided."],
            retrieval_context=rag_context,
            expected_output=None,
        )
        tone_test_case = LLMTestCase(
            input=_tone_evaluation_input(expected_agent_persona),
            actual_output=transcript_text,
            context=None,
            retrieval_context=None,
            expected_output=None,
        )

        # Build ConversationalTestCase for ConversationalGEval
        turns = []
        pending_user_messages: list[str] = []
        for t in transcript:
            role = _message_value(t, "role")
            content = str(_message_value(t, "content") or "")
            if role in {"simulated_user", "user"}:
                pending_user_messages.append(content)
            elif role == "agent":
                turns.append(LLMTestCase(
                    input="\n".join(pending_user_messages),
                    actual_output=content,
                ))
                pending_user_messages = []
        if pending_user_messages:
            turns.append(LLMTestCase(input="\n".join(pending_user_messages), actual_output=""))
        conversational_test_case = ConversationalTestCase(turns=turns)

        turn_cases: list[tuple[LLMTestCase, Any, int]] = []
        pending_user_messages = []
        pending_user_start: int | None = None
        for message_index, message in enumerate(transcript):
            role = _message_value(message, "role")
            if role in {"simulated_user", "user"}:
                if pending_user_start is None:
                    pending_user_start = message_index
                pending_user_messages.append(str(_message_value(message, "content") or ""))
            elif role == "agent" and pending_user_messages:
                turn_cases.append((LLMTestCase(
                    input="\n".join(pending_user_messages),
                    actual_output=str(_message_value(message, "content") or ""),
                    context=_turn_evaluation_context(
                        persona,
                        transcript[:pending_user_start] if pending_user_start is not None else [],
                        pending_user_messages,
                    ),
                ), message, message_index))
                pending_user_messages = []
                pending_user_start = None

        metrics = (
            _build_metrics(persona, rag_context, expected_agent_persona)
            if expected_agent_persona is not None
            else _build_metrics(persona, rag_context)
        )
        results: list[MetricResult] = []

        logger.info("[EVALUATION START]")
        
        for metric in metrics:
            metric_start = time.perf_counter()
            metric_name_str = _metric_name(metric)
            logger.info(f"[EVAL METRIC START] {metric_name_str}")
            
            judge_calls: list[dict[str, Any]] = []
            try:
                capture_token = _start_judge_capture()
                turn_scores: list[tuple[float, str, Any, int]] = []
                try:
                    if isinstance(metric, ConversationalGEval):
                        metric.measure(conversational_test_case)
                    elif metric_name_str in {"Answer Relevancy", "Intent Understanding", "Response Quality", "Completeness"} and turn_cases:
                        for turn_case, agent_message, message_index in turn_cases:
                            metric.measure(turn_case)
                            turn_scores.append((float(metric.score), str(metric.reason or ""), agent_message, message_index))
                    else:
                        metric.measure(tone_test_case if metric_name_str == "Persona and Tone Adherence" else test_case)
                finally:
                    judge_calls = _finish_judge_capture(capture_token)
                    
                metric_elapsed = time.perf_counter() - metric_start
                logger.info(f"[EVAL METRIC END] {metric_name_str} duration={metric_elapsed:.3f}s")
                
                raw_score = sum(item[0] for item in turn_scores) / len(turn_scores) if turn_scores else float(metric.score)
                weakest_turn = min(turn_scores, key=lambda item: item[0]) if turn_scores else None
                reason = (
                    f"Mean of {len(turn_scores)} user-agent exchanges. "
                    f"Lowest-scoring response: {weakest_turn[1]}"
                    if weakest_turn else metric.reason or ""
                )
                reference = (
                    _metric_reference(
                        transcript, metric_name_str,
                        explicit_turn_index=_message_turn_index(weakest_turn[2], weakest_turn[3]),
                        explicit_message_id=_message_value(weakest_turn[2], "message_id") or _message_value(weakest_turn[2], "id"),
                    ) if weakest_turn else _metric_reference(transcript, metric_name_str, metric_reason=metric.reason or "")
                )
                
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
                        reason=reason,
                        passed=bool(normalized_score >= _metric_threshold(metric_name_str, "rag" if _is_rag_metric(metric) else "base")),
                        threshold=_metric_threshold(metric_name_str, "rag" if _is_rag_metric(metric) else "base"),
                        category="rag" if _is_rag_metric(metric) else "base",
                        evidence_source="reference_context" if rag_context and _is_rag_metric(metric) else None,
                        diagnostics=_metric_diagnostics(
                            metric_name_str, raw_score, str(metric.reason or ""), reason, normalized_score,
                            turn_scores, judge_calls,
                        ),
                        **reference,
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
                        evaluation_status="error",
                        evidence_status="unverified",
                        diagnostics={
                            "metric_name": metric_name_str,
                            "judge_invocations": judge_calls,
                            "raw_score": None,
                            "raw_reason": None,
                            "aggregated_score": None,
                            "evidence_adjustments": [],
                            "conversation_penalty_adjustments": [],
                            "final_score": None,
                            "final_evaluation_status": "error",
                            "final_explanation": f"Metric failed to evaluate: {type(e).__name__}",
                            "referenced_message_ids": [],
                        },
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

                    judge_calls = []
                    try:
                        capture_token = _start_judge_capture()
                        try:
                            metric.measure(rag_test_case)
                        finally:
                            judge_calls = _finish_judge_capture(capture_token)

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
                                passed=bool(normalized_score >= _metric_threshold(metric_name_str, "rag")),
                                threshold=_metric_threshold(metric_name_str, "rag"),
                                category="rag",
                                evidence_source=str(turn_evidence.get("source") or "agent_retrieval"),
                                evaluation_status="evaluated",
                                diagnostics=_metric_diagnostics(
                                    result_name, raw_score, str(metric.reason or ""),
                                    str(metric.reason or ""), normalized_score, [], judge_calls,
                                ),
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
                                evaluation_status="error",
                                evidence_status="unverified",
                                diagnostics={
                                    "metric_name": result_name,
                                    "judge_invocations": judge_calls,
                                    "raw_score": None,
                                    "raw_reason": None,
                                    "aggregated_score": None,
                                    "evidence_adjustments": [],
                                    "conversation_penalty_adjustments": [],
                                    "final_score": None,
                                    "final_evaluation_status": "error",
                                    "final_explanation": f"Metric failed to evaluate: {type(e).__name__}",
                                    "referenced_message_ids": [],
                                },
                                **_metric_reference(
                                    transcript,
                                    result_name,
                                    explicit_turn_index=turn_evidence.get("turn_index"),
                                    explicit_message_id=turn_evidence.get("conversation_message_id"),
                                ),
                            )
                        )

        _apply_evidence_assessments(results, transcript)
        _apply_conversation_experience_penalties(results, transcript)
        _finalize_metric_diagnostics(results)
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
        explicit_message = _message_at_turn(transcript, explicit_turn_index)
        if explicit_message is None:
            return {}
        resolved_id = _message_identity(explicit_message, explicit_turn_index)
        if explicit_message_id and str(explicit_message_id) != resolved_id:
            return {}
        return {
            "turn_index": explicit_turn_index,
            "conversation_message_id": resolved_id,
        }

    target = _message_referenced_by_metric_reason(transcript, metric_name, metric_reason)
    if target is None:
        return {}
    turn_index = _message_turn_index(target, max(0, len(transcript) - 1))
    return {
        "turn_index": turn_index,
        "conversation_message_id": _message_identity(target, turn_index),
    }


def _apply_conversation_experience_penalties(results: list[MetricResult], transcript: list[Any]) -> None:
    repeated = _repeated_question_findings(transcript)
    restarts = _restart_findings(transcript)
    findings_by_metric = {
        "conversational quality": _unique_findings(repeated + restarts),
        "context retention": repeated,
        "multi-turn consistency": restarts,
    }
    for result in results:
        findings = findings_by_metric.get(str(result.name or "").lower())
        if not findings:
            continue
        penalty_text = "Full-conversation penalty: " + "; ".join(item.text for item in findings)
        cap = 0.55 if result.name.lower() in {"context retention", "multi-turn consistency"} else 0.65
        if result.score > cap:
            previous_score = result.score
            result.score = round(cap, 3)
            _add_diagnostic_adjustment(
                result, "conversation_penalty_adjustments",
                {"kind": "score_cap", "before": previous_score, "after": result.score, "findings": [item.text for item in findings]},
            )
        result.passed = bool(result.score >= result.threshold)
        result.reason = f"{result.reason} {penalty_text}".strip() if result.reason else penalty_text
        decisive = findings[0]
        result.turn_index = decisive.turn_index
        result.conversation_message_id = decisive.message_id


def _apply_evidence_assessments(results: list[MetricResult], transcript: list[Any]) -> None:
    factual = assess_factual_claims(transcript)
    contradictions = detect_structured_contradictions(transcript)
    numerical = validate_numerical_evidence(transcript)
    technical_errors = classify_technical_errors(transcript=transcript)

    hallucination = next(
        (result for result in results if result.name == "Hallucination" and result.category != "rag"),
        None,
    )
    factual_evidence = factual + numerical
    confirmed_factual_failures = [item for item in factual_evidence if item.status in {"contradicted", "unsupported"}]
    if hallucination is not None:
        hallucination.evidence = [item.model_dump(mode="json") for item in factual_evidence] or None
        if confirmed_factual_failures:
            hallucination.evaluation_status = "evaluated"
            hallucination.evidence_status = "contradicted" if any(item.status == "contradicted" for item in confirmed_factual_failures) else "unsupported"
            previous_score = hallucination.score
            hallucination.score = min(hallucination.score, 0.55)
            _add_diagnostic_adjustment(
                hallucination, "evidence_adjustments",
                {"kind": "confirmed_factual_failure", "before": previous_score, "after": hallucination.score},
            )
            hallucination.passed = bool(hallucination.score >= (hallucination.threshold or _metric_threshold("Hallucination")))
            first = confirmed_factual_failures[0]
            hallucination.reason = _append_reason(
                hallucination.reason,
                f"Confirmed {first.kind} evidence: claimed={first.actual!r}, verified={first.expected!r}.",
            )
            _set_metric_reference_from_evidence(hallucination, first, transcript)
        elif factual_evidence and all(item.status == "supported" for item in factual_evidence):
            hallucination.evaluation_status = "evaluated"
            hallucination.evidence_status = "supported"
            hallucination.reason = _append_reason(hallucination.reason, "Available independent evidence supports the assessed factual claims.")
        else:
            hallucination.evaluation_status = "not_evaluated"
            hallucination.evidence_status = "unverified"
            explanation = "Independent factual evidence was unavailable; the conversation was not classified as confirmed hallucination."
            if technical_errors:
                explanation = "A technical failure was observed and was classified separately; it was not treated as hallucination."
            hallucination.reason = _append_reason(hallucination.reason, explanation)
            _add_diagnostic_adjustment(
                hallucination, "evidence_adjustments",
                {"kind": "insufficient_evidence", "score_changed": False, "status": "not_evaluated"},
            )

    confirmed_accuracy_failures = [item for item in factual_evidence if item.status == "contradicted"]
    if confirmed_accuracy_failures:
        response_quality = next((result for result in results if result.name == "Response Quality"), None)
        if response_quality is not None:
            first = confirmed_accuracy_failures[0]
            response_quality.evidence = [item.model_dump(mode="json") for item in confirmed_accuracy_failures]
            response_quality.evidence_status = "contradicted"
            previous_score = response_quality.score
            response_quality.score = min(response_quality.score, 0.65)
            response_quality.passed = bool(
                response_quality.score >= (response_quality.threshold or _metric_threshold("Response Quality"))
            )
            response_quality.reason = _append_reason(
                response_quality.reason,
                f"Independent evidence contradicts the response: claimed={first.actual!r}, verified={first.expected!r}.",
            )
            _add_diagnostic_adjustment(
                response_quality, "evidence_adjustments",
                {"kind": "confirmed_accuracy_failure", "before": previous_score, "after": response_quality.score},
            )
            _set_metric_reference_from_evidence(response_quality, first, transcript)

    confirmed_contradictions = [item for item in contradictions if item.status == "contradicted"]
    if confirmed_contradictions:
        consistency = next((result for result in results if result.name == "Multi-turn Consistency"), None)
        if consistency is not None:
            consistency.evidence = [item.model_dump(mode="json") for item in confirmed_contradictions]
            consistency.evidence_status = "contradicted"
            consistency.evaluation_status = "evaluated"
            previous_score = consistency.score
            consistency.score = min(consistency.score, 0.55)
            _add_diagnostic_adjustment(
                consistency, "evidence_adjustments",
                {"kind": "confirmed_contradiction", "before": previous_score, "after": consistency.score},
            )
            consistency.passed = bool(consistency.score >= (consistency.threshold or _metric_threshold("Multi-turn Consistency")))
            consistency.reason = _append_reason(
                consistency.reason,
                "Confirmed contradiction between compatible claims: " + ", ".join(item.claim or "claim" for item in confirmed_contradictions),
            )
            _set_metric_reference_from_evidence(consistency, confirmed_contradictions[0], transcript)
    else:
        consistency = next((result for result in results if result.name == "Multi-turn Consistency"), None)
        if consistency is not None and _reason_alleges_contradiction(consistency.reason):
            consistency.evidence_status = "unverified"
            consistency.reason = _append_reason(
                consistency.reason,
                "The contradiction claim was not confirmed by compatible structured evidence and remains uncertain.",
            )
            _add_diagnostic_adjustment(
                consistency, "evidence_adjustments",
                {"kind": "unverified_contradiction_claim", "score_changed": False},
            )


def _set_metric_reference_from_evidence(result: MetricResult, evidence: Any, transcript: list[Any]) -> None:
    if not evidence.message_ids:
        return
    message_id = evidence.message_ids[-1]
    for index, message in enumerate(transcript):
        if _message_identity(message, _message_turn_index(message, index)) == message_id:
            result.conversation_message_id = message_id
            result.turn_index = _message_turn_index(message, index)
            return


def _append_reason(current: str, addition: str) -> str:
    return f"{current} {addition}".strip() if current else addition


def _turn_evaluation_context(
    persona: Persona,
    prior_messages: list[Any],
    current_user_messages: list[str] | None = None,
) -> list[str]:
    context = ["Active user request: use only the current Input field; it is intentionally kept separate from prior Context."]
    if not prior_messages:
        context.append(f"Original scenario goal (initial-turn context only): {persona.goal}")
    else:
        context.append("The active task may continue, clarify, correct, or replace an earlier task; decide from the current Input and prior conversation.")
    if prior_messages:
        context.append("Prior conversation:\n" + _transcript_to_text(prior_messages))
    else:
        context.append("Prior conversation: none")
    return context


def _metric_diagnostics(
    metric_name: str,
    raw_score: float,
    raw_reason: str,
    aggregated_reason: str,
    aggregated_score: float,
    turn_scores: list[tuple[float, str, Any, int]],
    judge_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "metric_name": metric_name,
        "judge_invocations": judge_calls,
        "raw_score": round(raw_score, 6),
        "raw_reason": raw_reason,
        "turn_results": [
            {
                "score": round(score, 6),
                "reason": reason,
                "turn_index": _message_turn_index(message, index),
                "conversation_message_id": _message_identity(message, _message_turn_index(message, index)),
            }
            for score, reason, message, index in turn_scores
        ],
        "aggregated_score": round(aggregated_score, 6),
        "aggregated_reason": aggregated_reason,
        "evidence_adjustments": [],
        "conversation_penalty_adjustments": [],
        "final_score": None,
        "final_evaluation_status": None,
        "final_explanation": None,
        "referenced_message_ids": [],
    }


def _add_diagnostic_adjustment(result: MetricResult, key: str, adjustment: dict[str, Any]) -> None:
    if result.diagnostics is None:
        result.diagnostics = {"evidence_adjustments": [], "conversation_penalty_adjustments": []}
    result.diagnostics.setdefault(key, []).append(adjustment)


def _finalize_metric_diagnostics(results: list[MetricResult]) -> None:
    for result in results:
        if result.diagnostics is None:
            result.diagnostics = {"evidence_adjustments": [], "conversation_penalty_adjustments": []}
        result.diagnostics["final_score"] = None if result.evaluation_status in {"not_evaluated", "error"} else result.score
        result.diagnostics["final_evaluation_status"] = result.evaluation_status or "evaluated"
        result.diagnostics["final_explanation"] = result.reason
        result.diagnostics["referenced_message_ids"] = (
            [result.conversation_message_id] if result.conversation_message_id else []
        )


def _reason_alleges_contradiction(reason: str | None) -> bool:
    return bool(re.search(r"\bcontradict(?:ion|ory|s|ed|ing)?\b", str(reason or ""), re.I))


@dataclass(frozen=True)
class _ConversationFinding:
    text: str
    turn_index: int
    message_id: str


def _conversation_experience_findings(transcript: list[Any]) -> list[str]:
    findings = _unique_findings(_repeated_question_findings(transcript) + _restart_findings(transcript))
    return [item.text for item in findings]


def _repeated_question_findings(transcript: list[Any]) -> list[_ConversationFinding]:
    seen: list[tuple[str, int]] = []
    findings: list[_ConversationFinding] = []
    for turn, message in enumerate(transcript or []):
        if _message_value(message, "role") != "agent":
            continue
        text = str(_message_value(message, "content") or "")
        question = _normalized_question(text)
        if not question:
            continue
        previous = next(
            (previous_turn for previous_question, previous_turn in seen if _question_similarity(previous_question, question) >= 0.75),
            None,
        )
        if previous is not None and _has_substantive_user_response_between(transcript, previous, turn):
            findings.append(_ConversationFinding(
                text=f"Agent repeated a materially equivalent question after the user responded at turns {previous} and {turn}.",
                turn_index=_message_turn_index(message, turn),
                message_id=_message_identity(message, _message_turn_index(message, turn)),
            ))
        seen.append((question, turn))
    return findings


def _restart_findings(transcript: list[Any]) -> list[_ConversationFinding]:
    patterns = (
        "start over",
        "start again",
        "restart",
        "begin again",
        "from the beginning",
        "let's begin again",
        "let us begin again",
    )
    findings: list[_ConversationFinding] = []
    for turn, message in enumerate(transcript or []):
        if _message_value(message, "role") != "agent":
            continue
        text = str(_message_value(message, "content") or "")
        if any(pattern in text.lower() for pattern in patterns):
            resolved_turn = _message_turn_index(message, turn)
            findings.append(_ConversationFinding(
                text=f"Agent restarted or reset the workflow at turn {resolved_turn}.",
                turn_index=resolved_turn,
                message_id=_message_identity(message, resolved_turn),
            ))
    return findings


def _has_substantive_user_response_between(transcript: list[Any], start: int, end: int) -> bool:
    uncertainty = re.compile(r"^(?:i\s+)?(?:do not|don't|dont|cannot|can't|cant)\s+(?:know|have|remember)|^not sure\b", re.I)
    for message in transcript[start + 1:end]:
        if _message_value(message, "role") not in {"simulated_user", "user"}:
            continue
        content = str(_message_value(message, "content") or "").strip()
        if len(content) >= 2 and not uncertainty.search(content):
            return True
    return False


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
    lowered = str(text or "").lower()
    for phrase in ("let's start over", "let us start over", "start over", "start again", "begin again", "from the beginning"):
        lowered = lowered.replace(phrase, " ")
    question = " ".join(part.strip() for part in re.split(r"[.!]", lowered) if "?" in part or _looks_like_question(part))
    question = re.sub(r"[^a-z0-9 ]+", "", question.lower())
    question = re.sub(r"\s+", " ", question).strip()
    return question if len(question) >= 12 else ""


def _question_similarity(left: str, right: str) -> float:
    stop_words = {"a", "an", "the", "what", "which", "would", "could", "can", "you", "please"}
    left_tokens = {token for token in left.split() if token not in stop_words}
    right_tokens = {token for token in right.split() if token not in stop_words}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


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


def _unique_findings(findings: list[_ConversationFinding]) -> list[_ConversationFinding]:
    unique: list[_ConversationFinding] = []
    seen: set[str] = set()
    for finding in findings:
        if finding.text in seen:
            continue
        seen.add(finding.text)
        unique.append(finding)
    return unique[:5]


def _message_referenced_by_metric_reason(transcript: list[Any], metric_name: str, metric_reason: str | None) -> Any:
    normalized_metric = _normalize_match_text(f"{metric_name} {metric_reason or ''}")
    candidates = _messages_for_metric_match(transcript, metric_name)
    best = None
    best_score = 0.0
    for message in candidates:
        content = _normalize_match_text(_message_value(message, "content"))
        if not content:
            continue
        score = 0.0
        for fragment in _meaningful_fragments(normalized_metric):
            if fragment in content:
                score = max(score, float(len(fragment)))
        reason_tokens = _reference_tokens(normalized_metric)
        content_tokens = _reference_tokens(content)
        shared = reason_tokens & content_tokens
        if len(shared) >= 3:
            score = max(score, 12.0 + (len(shared) / max(1, len(content_tokens))))
        if score > best_score:
            best = message
            best_score = score
    return best if best_score >= 12 else None


def _reference_tokens(text: str) -> set[str]:
    ignored = {
        "the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "with", "that",
        "agent", "assistant", "user", "response", "failed", "failure", "answer", "replied",
    }
    return {
        token for token in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(token) >= 3 and token not in ignored
    }


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
