from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app import evaluator
from app.evaluation_service import _expected_agent_persona
from app.report_engine import _normalize_metric
from app.schemas import AgentConfig, MetricResult, Persona, TestScenario


def _persona() -> Persona:
    return Persona(
        name="Alex",
        goal="Resolve the customer's current support request.",
        tone="professional and concise",
    )


class _MetricDefinition:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _metric(name: str, score: float = 0.8, reason: str = "Measured."):
    class Metric:
        def __init__(self):
            self.name = name
            self.score = score
            self.reason = reason

        def measure(self, test_case):
            self.score = score
            self.reason = reason

    return Metric()


def test_simulated_customer_persona_is_not_an_agent_requirement():
    text = evaluator._full_conversation_input(_persona(), None)
    assert "Simulated-user profile (not agent requirements)" in text
    assert "No explicit agent persona is configured" in text

    with patch.object(evaluator, "get_judge", return_value=object()), \
         patch.object(evaluator, "GEval", _MetricDefinition), \
         patch.object(evaluator, "ConversationalGEval", _MetricDefinition):
        tone = next(item for item in evaluator._build_metrics(_persona(), None) if item.name == "Persona and Tone Adherence")
    assert "do not invent one" in tone.criteria.lower()


def test_explicit_agent_persona_is_separate_and_backward_compatible():
    expected = {"role": "support specialist", "tone": "warm and direct"}
    text = evaluator._full_conversation_input(_persona(), expected)
    assert "Expected-agent behavior: role: support specialist; tone: warm and direct" in text

    scenario = TestScenario(
        scenario_id="agent-persona-test",
        agent=AgentConfig(config={"expected_agent_persona": expected}),
        persona=_persona(),
    )
    assert _expected_agent_persona(scenario) == expected


def test_turn_context_uses_goal_only_for_initial_exchange_and_never_future_turns(monkeypatch):
    captured = []
    metric = _metric("Intent Understanding")
    metric.measure = lambda test_case: captured.append(test_case)
    monkeypatch.setattr(evaluator, "_build_metrics", lambda persona, rag_context: [metric])
    transcript = [
        {"role": "user", "content": "Help with my account.", "message_id": "u1"},
        {"role": "agent", "content": "Which account?", "message_id": "a1"},
        {"role": "user", "content": "Actually, what are your opening hours?", "message_id": "u2"},
        {"role": "agent", "content": "We open at nine.", "message_id": "a2"},
    ]
    evaluator.evaluate_transcript(_persona(), transcript)

    assert "Original scenario goal" in "\n".join(captured[0].context)
    later = "\n".join(captured[1].context)
    assert "Original scenario goal" not in later
    assert "Actually, what are your opening hours?" in captured[1].input
    assert "Actually, what are your opening hours?" not in later
    assert "We open at nine." not in later
    assert "User: Help with my account." in later
    assert "Agent: Which account?" in later


def test_unverified_judge_contradiction_is_not_presented_as_confirmed():
    result = MetricResult(
        name="Multi-turn Consistency", score=0.2, passed=False,
        reason="The assistant contradicted its earlier statement.", threshold=0.75,
    )
    evaluator._apply_evidence_assessments([result], [
        {"role": "agent", "content": "No records for March.", "message_id": "a1"},
        {"role": "agent", "content": "One record for April.", "message_id": "a2"},
    ])
    assert result.evidence_status == "unverified"
    assert "not confirmed" in result.reason
    assert result.score == 0.2


def test_structured_same_scope_contradiction_is_confirmed():
    result = MetricResult(name="Multi-turn Consistency", score=0.9, passed=True, reason="Consistent.", threshold=0.75)
    transcript = [
        {"role": "agent", "content": "Open", "message_id": "a1", "metadata": {"claims": [{"entity": "ticket-1", "attribute": "status", "scope": "current", "timeframe": "today", "value": "OPEN"}]}},
        {"role": "agent", "content": "Closed", "message_id": "a2", "metadata": {"claims": [{"entity": "ticket-1", "attribute": "status", "scope": "current", "timeframe": "today", "value": "CLOSED"}]}},
    ]
    evaluator._apply_evidence_assessments([result], transcript)
    assert result.evidence_status == "contradicted"
    assert result.conversation_message_id == "a2"
    assert result.score == 0.55


def test_diagnostics_trace_raw_turn_aggregate_and_final_scores(monkeypatch):
    scores = iter([(0.9, "Good."), (0.3, "Missed the request.")])

    class TurnMetric:
        name = "Answer Relevancy"
        score = 0.0
        reason = ""

        def measure(self, test_case):
            self.score, self.reason = next(scores)

    monkeypatch.setattr(evaluator, "_build_metrics", lambda persona, rag_context: [TurnMetric()])
    results = evaluator.evaluate_transcript(_persona(), [
        {"role": "user", "content": "First", "message_id": "u1"},
        {"role": "agent", "content": "First answer", "message_id": "a1"},
        {"role": "user", "content": "Second", "message_id": "u2"},
        {"role": "agent", "content": "Wrong answer", "message_id": "a2"},
    ])
    diagnostic = results[0].diagnostics
    assert diagnostic["raw_score"] == 0.6
    assert [turn["score"] for turn in diagnostic["turn_results"]] == [0.9, 0.3]
    assert diagnostic["aggregated_score"] == 0.6
    assert diagnostic["final_score"] == 0.6
    assert diagnostic["referenced_message_ids"] == ["a2"]


def test_judge_provenance_records_primary_and_fallback(monkeypatch):
    class Message:
        content = '{"score": 1, "reason": "ok"}'

    class Completion:
        choices = [type("Choice", (), {"message": Message()})()]

    class Completions:
        def create(self, **kwargs):
            return Completion()

    judge = evaluator.GroqJudge.__new__(evaluator.GroqJudge)
    judge.model_name = "primary-model"
    judge.client = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
    judge._fallback = None
    token = evaluator._start_judge_capture()
    judge.generate("return json")
    calls = evaluator._finish_judge_capture(token)
    assert calls == [{"provider": "groq", "model": "primary-model", "fallback_used": False, "temperature": 0.5, "reasoning_effort": "low", "status": "success"}]

    class FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("primary unavailable")

    class Fallback:
        def generate(self, prompt):
            return '{"score": 1, "reason": "fallback"}'

        def get_model_name(self):
            return "fallback-model"

    judge.client = type("Client", (), {"chat": type("Chat", (), {"completions": FailingCompletions()})()})()
    judge._fallback = Fallback()
    token = evaluator._start_judge_capture()
    judge.generate("return json")
    calls = evaluator._finish_judge_capture(token)
    assert calls[0]["provider"] == "gemini"
    assert calls[0]["fallback_used"] is True
    assert calls[0]["primary_error"] == "RuntimeError"


def test_unavailable_metric_renders_na_in_reports_and_dashboard():
    normalized = _normalize_metric({
        "name": "Hallucination", "score": 1.0, "passed": True,
        "evaluation_status": "not_evaluated",
    })
    assert normalized["score"] is None
    assert normalized["status"] == "NOT EVALUATED"

    source = Path("frontend/static/app.js").read_text(encoding="utf-8")
    assert 'scoreAvailable ? fmtScore(m.score) : "N/A"' in source


def test_metric_result_diagnostics_is_optional_for_historical_payloads():
    historical = MetricResult(name="Goal Completion", score=0.5, reason="Old", passed=False)
    assert historical.diagnostics is None


def test_tone_metric_receives_only_agent_communication_expectations(monkeypatch):
    captured = []
    metric = _metric("Persona and Tone Adherence")
    metric.measure = lambda test_case: captured.append(test_case)
    monkeypatch.setattr(evaluator, "_build_metrics", lambda persona, rag_context, expected: [metric])

    evaluator.evaluate_transcript(
        _persona(),
        [
            {"role": "user", "content": "Cancel order 42.", "message_id": "u1"},
            {"role": "agent", "content": "I am sorry, but I cannot cancel it here.", "message_id": "a1"},
        ],
        expected_agent_persona={"tone": "professional and respectful"},
    )

    assert len(captured) == 1
    assert "professional and respectful" in captured[0].input
    assert "Cancel order 42" not in captured[0].input
    assert "Resolve the customer's current support request" not in captured[0].input


def test_metric_definitions_keep_tone_relevance_and_hallucination_isolated():
    with patch.object(evaluator, "get_judge", return_value=object()), \
         patch.object(evaluator, "GEval", _MetricDefinition), \
         patch.object(evaluator, "ConversationalGEval", _MetricDefinition):
        metrics = {item.name: item for item in evaluator._build_metrics(_persona(), None)}

    tone_steps = " ".join(metrics["Persona and Tone Adherence"].evaluation_steps).lower()
    relevancy_steps = " ".join(metrics["Answer Relevancy"].evaluation_steps).lower()
    hallucination = metrics["Hallucination"]
    assert "wrong task" in tone_steps
    assert "not completeness" in relevancy_steps
    assert "higher score means no established fabrication" in hallucination.criteria.lower()


def test_confirmed_numerical_error_reduces_response_quality_and_sets_reference():
    result = MetricResult(
        name="Response Quality", score=1.0, passed=True,
        reason="Clear and concise.", threshold=0.75,
    )
    transcript = [{
        "role": "agent", "content": "Found 5 records.", "message_id": "a-count",
        "metadata": {
            "components": [{"type": "table", "complete": True, "rows": [{}, {}, {}]}],
            "numerical_claims": [{"operation": "count", "claimed_value": 5}],
        },
    }]

    evaluator._apply_evidence_assessments([result], transcript)

    assert result.score == 0.65
    assert result.passed is False
    assert result.evidence_status == "contradicted"
    assert result.conversation_message_id == "a-count"
    assert "claimed=5" in result.reason


