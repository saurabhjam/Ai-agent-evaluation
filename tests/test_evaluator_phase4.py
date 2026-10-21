from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from deepeval.metrics import GEval
from deepeval.models.base_model import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

from app import evaluator
from app.evaluation_service import _balanced_overall_score
from app.failure_analysis.engine import FailureAnalysisEngine
from app.report_engine import _normalize_metric
from app.schemas import MetricResult, Persona


class _CapturingJudge(DeepEvalBaseLLM):
    def __init__(self):
        self.prompts: list[str] = []
        super().__init__(model_name="capturing-judge")

    def load_model(self):
        return self

    def generate(self, prompt: str, schema=None):
        self.prompts.append(prompt)
        if schema is not None:
            return schema(score=8, reason="Captured fields were evaluated.")
        return '{"score": 8, "reason": "Captured fields were evaluated."}'

    async def a_generate(self, prompt: str, schema=None):
        return self.generate(prompt, schema=schema)

    def get_model_name(self):
        return "capturing-judge"


def _persona() -> Persona:
    return Persona(
        name="Casey",
        goal="Resolve the customer's current account request.",
        tone="calm and professional",
    )


def test_installed_deepeval_prompt_contains_only_declared_evaluation_params():
    judge = _CapturingJudge()
    metric = GEval(
        name="Context Mapping",
        criteria="Check the supplied fields.",
        evaluation_steps=["Inspect all supplied fields."],
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.CONTEXT,
        ],
        model=judge,
        async_mode=False,
    )
    metric.measure(LLMTestCase(
        input="CURRENT USER REQUEST",
        actual_output="CURRENT AGENT RESPONSE",
        context=["ORIGINAL SCENARIO GOAL", "PRIOR CONVERSATION"],
    ))

    prompt = judge.prompts[-1]
    assert "CURRENT USER REQUEST" in prompt
    assert "CURRENT AGENT RESPONSE" in prompt
    assert "ORIGINAL SCENARIO GOAL" in prompt
    assert "PRIOR CONVERSATION" in prompt


def test_metric_definitions_declare_required_context_without_changing_thresholds():
    class _MetricDefinition:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    with patch.object(evaluator, "get_judge", return_value=object()), \
         patch.object(evaluator, "GEval", _MetricDefinition), \
         patch.object(evaluator, "ConversationalGEval", _MetricDefinition):
        metrics = evaluator._build_metrics(_persona(), None)

    by_name = {metric.name: metric for metric in metrics}
    assert by_name["Persona and Tone Adherence"].evaluation_params == [
        LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT,
    ]
    for name in ("Intent Understanding", "Answer Relevancy", "Completeness"):
        assert LLMTestCaseParams.CONTEXT in by_name[name].evaluation_params
    assert LLMTestCaseParams.CONTEXT not in by_name["Response Quality"].evaluation_params
    assert by_name["Goal Completion"].threshold == evaluator.METRIC_CONFIG["Goal Completion"]["threshold"]
    assert by_name["Intent Understanding"].threshold == evaluator.METRIC_CONFIG["Intent Understanding"]["threshold"]


def test_turn_metrics_receive_goal_and_only_prior_conversation(monkeypatch):
    captured: list[LLMTestCase] = []

    class _IntentMetric:
        name = "Intent Understanding"
        score = 1.0
        reason = "Intent understood."

        def measure(self, test_case):
            captured.append(test_case)

    monkeypatch.setattr(evaluator, "_build_metrics", lambda persona, rag_context: [_IntentMetric()])
    transcript = [
        {"role": "user", "content": "Help with my account.", "message_id": "u-1"},
        {"role": "agent", "content": "Which account?", "message_id": "a-1"},
        {"role": "user", "content": "My business account.", "message_id": "u-2"},
        {"role": "agent", "content": "I will open the business account.", "message_id": "a-2"},
    ]

    evaluator.evaluate_transcript(_persona(), transcript)

    assert len(captured) == 2
    assert any("Active user request: use only the current Input field" in item for item in captured[0].context)
    assert any("Original scenario goal (initial-turn context only):" in item for item in captured[0].context)
    assert "Prior conversation: none" in captured[0].context
    second_context = "\n".join(captured[1].context)
    assert "Help with my account." in second_context
    assert "Which account?" in second_context
    assert "Original scenario goal" not in second_context
    assert "My business account." not in second_context
    assert "I will open the business account." not in second_context


def test_tone_prompt_is_isolated_from_relevance_and_execution():
    class _MetricDefinition:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    with patch.object(evaluator, "get_judge", return_value=object()), \
         patch.object(evaluator, "GEval", _MetricDefinition), \
         patch.object(evaluator, "ConversationalGEval", _MetricDefinition):
        metric = next(item for item in evaluator._build_metrics(_persona(), None) if item.name == "Persona and Tone Adherence")

    instructions = " ".join(metric.evaluation_steps).lower()
    assert "do not reduce the tone score" in instructions
    assert "irrelevant" in instructions
    assert "factually wrong" in instructions


def test_metric_execution_error_is_excluded_from_score_and_failure_analysis():
    error_metric = MetricResult(
        name="Intent Understanding",
        score=0.0,
        passed=False,
        reason="Metric failed to evaluate: TimeoutError",
        threshold=0.75,
        category="base",
        evaluation_status="error",
        evidence_status="unverified",
    )
    valid_metric = MetricResult(
        name="Goal Completion", score=0.8, passed=True, reason="Completed.", threshold=0.8, category="base",
    )

    assert _balanced_overall_score([error_metric, valid_metric]) == 0.8
    assert FailureAnalysisEngine().generate(metrics=[error_metric, valid_metric]) == []
    normalized = _normalize_metric(error_metric.model_dump(mode="json"), 0.7)
    assert normalized["status"] == "ERROR"
    assert normalized["passed"] is None


def test_frontend_does_not_map_unavailable_metrics_to_failure():
    source = Path("frontend/static/app.js").read_text(encoding="utf-8")
    assert 'm.evaluation_status === "not_evaluated"' in source
    assert 'm.evaluation_status === "error"' in source
    assert "NOT EVALUATED" in source
    assert "mErrors" in source
