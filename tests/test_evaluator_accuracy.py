from app import evaluator
from app.schemas import MetricResult, Persona
from app.report_engine import _capability_matrix
from app.failure_analysis.engine import FailureAnalysisEngine


def _persona():
    return Persona(name="Customer", goal="Find matching records", tone="polite")


def test_turn_metric_averages_exchanges_and_references_weakest_agent(monkeypatch):
    class TurnMetric:
        name = "Answer Relevancy"
        reason = ""
        score = 0.0

        def measure(self, case):
            self.score = 0.2 if case.actual_output == "Unrelated answer" else 1.0
            self.reason = "Off topic" if self.score == 0.2 else "Direct answer"

    class GoalMetric:
        name = "Goal Completion"
        reason = "Original goal reviewed"
        score = 0.8

        def measure(self, case):
            assert "User: First question" in case.actual_output
            assert "Agent: No matching records" in case.actual_output

    monkeypatch.setattr(evaluator, "_build_metrics", lambda persona, rag_context: [GoalMetric(), TurnMetric()])
    transcript = [
        {"role": "simulated_user", "content": "First question", "turn_index": 0, "id": "u-1"},
        {"role": "agent", "content": "Unrelated answer", "turn_index": 1, "id": "a-1"},
        {"role": "simulated_user", "content": "Find matching records", "turn_index": 2, "id": "u-2"},
        {"role": "agent", "content": "No matching records", "turn_index": 3, "id": "a-2"},
    ]

    results = {item.name: item for item in evaluator.evaluate_transcript(_persona(), transcript)}

    assert results["Answer Relevancy"].score == 0.6
    assert results["Answer Relevancy"].passed is False
    assert results["Answer Relevancy"].conversation_message_id == "a-1"
    assert results["Answer Relevancy"].turn_index == 1
    assert results["Goal Completion"].score == 0.8


def test_unrelated_outcomes_do_not_trigger_contradiction_penalty():
    transcript = [
        {"role": "simulated_user", "content": "Show last month", "turn_index": 0},
        {"role": "agent", "content": "Found 4 records last month.", "turn_index": 1},
        {"role": "simulated_user", "content": "Show this month", "turn_index": 2},
        {"role": "agent", "content": "No matching records this month.", "turn_index": 3},
    ]
    result = MetricResult(name="Multi-turn Consistency", score=1.0, passed=True, reason="Consistent", threshold=0.75)

    evaluator._apply_conversation_experience_penalties([result], transcript)

    assert result.score == 1.0
    assert result.passed is True
    assert "contradict" not in result.reason.lower()


def test_explicit_restart_only_affects_consistency():
    transcript = [
        {"role": "simulated_user", "content": "Continue the task", "turn_index": 0},
        {"role": "agent", "content": "Let's start over.", "turn_index": 1},
    ]
    results = [
        MetricResult(name=name, score=1.0, passed=True, reason="", threshold=0.75)
        for name in ("Multi-turn Consistency", "Context Retention", "Hallucination", "Goal Completion")
    ]

    evaluator._apply_conversation_experience_penalties(results, transcript)

    assert results[0].score == 0.55
    assert results[0].passed is False
    assert all(item.score == 1.0 for item in results[1:])


def test_legitimate_clarification_is_not_penalized():
    transcript = [
        {"role": "simulated_user", "content": "I need help with my account.", "turn_index": 0},
        {"role": "agent", "content": "Which account do you need help with?", "turn_index": 1},
        {"role": "simulated_user", "content": "My business account.", "turn_index": 2},
        {"role": "agent", "content": "What issue are you seeing in the business account?", "turn_index": 3},
    ]
    results = [
        MetricResult(name=name, score=1.0, passed=True, reason="", threshold=0.75)
        for name in ("Conversational Quality", "Context Retention", "Multi-turn Consistency")
    ]

    evaluator._apply_conversation_experience_penalties(results, transcript)

    assert all(item.score == 1.0 for item in results)
    assert all(item.passed is True for item in results)
    assert all("Full-conversation penalty" not in item.reason for item in results)


def test_report_capability_matrix_uses_base_metric_scores():
    matrix = _capability_matrix(
        {"metrics": [{"name": "Answer Relevancy", "category": "base", "score": 0.8}]},
        [],
    )

    assert matrix[0]["capability"] == "Conversation"
    assert matrix[0]["status"] == "Good"
    assert matrix[2]["status"] == "Not Evaluated"


def test_failure_analysis_does_not_invent_last_turn_or_confirm_cause():
    metric = MetricResult(
        name="Answer Relevancy", score=0.2, passed=False,
        reason="The response was off topic.", threshold=0.75, category="base",
    )
    conversation = [
        {"speaker": "user", "message": "First question", "turn_index": 0, "message_id": "u-1"},
        {"speaker": "agent", "message": "Unrelated reply", "turn_index": 1, "message_id": "a-1"},
    ]

    failure = FailureAnalysisEngine().generate(metrics=[metric], conversation=conversation)[0]

    assert failure.conversation_turn is None
    assert failure.conversation_message_id is None
    assert failure.conversation_snippet is None
    assert failure.root_cause.startswith("Possible cause (not confirmed):")


def test_failure_analysis_resolves_stable_message_id_before_turn_number():
    metric = MetricResult(
        name="Answer Relevancy", score=0.2, passed=False,
        reason="The response was off topic.", threshold=0.75, category="base",
        turn_index=20, conversation_message_id="a-20",
    )
    conversation = [
        {"speaker": "user", "message": "Question", "turn_index": 19, "message_id": "u-19"},
        {"speaker": "agent", "message": "Wrong answer", "turn_index": 20, "message_id": "a-20"},
        {"speaker": "user", "message": "Follow-up", "turn_index": 21, "message_id": "u-21"},
    ]

    failure = FailureAnalysisEngine().generate(metrics=[metric], conversation=conversation)[0]

    assert failure.conversation_turn == 1
    assert failure.conversation_message_id == "a-20"
    assert [item["message_id"] for item in failure.conversation_snippet] == ["u-19", "a-20", "u-21"]
