from __future__ import annotations

from app import evaluator
from app.failure_analysis.engine import FailureAnalysisEngine
from app.schemas import MetricResult
from tests.fixtures.conversation_accuracy_golden import GOLDEN_CONVERSATIONS


def test_golden_dataset_covers_required_cases_with_stable_ids():
    assert len(GOLDEN_CONVERSATIONS) == 25
    assert len({case["id"] for case in GOLDEN_CONVERSATIONS}) == 25
    for case in GOLDEN_CONVERSATIONS:
        ids = [message["message_id"] for message in case["messages"]]
        assert len(ids) == len(set(ids))
        assert case["goal"]
        assert case["expect"]


def test_metric_reference_does_not_guess_when_reason_has_no_relevant_evidence():
    transcript = [
        {"role": "user", "content": "Cancel order 42.", "message_id": "u-1", "turn_index": 0},
        {"role": "agent", "content": "Our opening hours are nine to six.", "message_id": "a-1", "turn_index": 1},
    ]
    assert evaluator._metric_reference(
        transcript,
        "Goal Completion",
        metric_reason="The original objective was not completed.",
    ) == {}


def test_metric_reference_rejects_nonexistent_explicit_message_or_turn():
    transcript = [{"role": "agent", "content": "Answer", "message_id": "a-1", "turn_index": 0}]
    assert evaluator._metric_reference(
        transcript, "Answer Relevancy", explicit_turn_index=4, explicit_message_id="missing",
    ) == {}
    assert evaluator._metric_reference(
        transcript, "Answer Relevancy", explicit_turn_index=0, explicit_message_id="wrong-id",
    ) == {}


def test_failure_analysis_drops_invalid_metric_message_id():
    metric = MetricResult(
        name="Answer Relevancy", score=0.2, passed=False, reason="Off topic.",
        threshold=0.75, conversation_message_id="not-in-conversation", turn_index=99,
    )
    conversation = [{"speaker": "agent", "message": "Actual response", "message_id": "a-1", "turn_index": 0}]
    failure = FailureAnalysisEngine().generate(metrics=[metric], conversation=conversation)[0]
    assert failure.conversation_message_id is None
    assert failure.conversation_turn is None
    assert failure.conversation_snippet is None


def test_repeated_answered_question_penalty_references_second_agent_message():
    transcript = [
        {"role": "agent", "content": "Which account should I use?", "message_id": "a-1", "turn_index": 0},
        {"role": "user", "content": "My business account.", "message_id": "u-1", "turn_index": 1},
        {"role": "agent", "content": "Which account should I use?", "message_id": "a-2", "turn_index": 2},
    ]
    metrics = [
        MetricResult(name=name, score=1.0, passed=True, reason="", threshold=0.75)
        for name in ("Conversational Quality", "Context Retention", "Intent Understanding")
    ]
    evaluator._apply_conversation_experience_penalties(metrics, transcript)
    assert metrics[0].conversation_message_id == "a-2"
    assert metrics[1].conversation_message_id == "a-2"
    assert metrics[0].turn_index == metrics[1].turn_index == 2
    assert metrics[2].score == 1.0


def test_repeated_unanswered_question_is_not_context_loss():
    transcript = [
        {"role": "agent", "content": "Which account should I use?", "message_id": "a-1"},
        {"role": "user", "content": "I don't know.", "message_id": "u-1"},
        {"role": "agent", "content": "Which account should I use?", "message_id": "a-2"},
    ]
    metric = MetricResult(name="Context Retention", score=1.0, passed=True, reason="", threshold=0.75)
    evaluator._apply_conversation_experience_penalties([metric], transcript)
    assert metric.score == 1.0
    assert metric.conversation_message_id is None


def test_restart_penalty_is_scoped_and_references_restart_message():
    transcript = [
        {"role": "user", "content": "Continue claim 88.", "message_id": "u-1"},
        {"role": "agent", "content": "Let's start over.", "message_id": "a-1"},
    ]
    metrics = [
        MetricResult(name=name, score=1.0, passed=True, reason="", threshold=0.75)
        for name in ("Conversational Quality", "Multi-turn Consistency", "Goal Completion", "Persona and Tone Adherence")
    ]
    evaluator._apply_conversation_experience_penalties(metrics, transcript)
    assert metrics[0].conversation_message_id == "a-1"
    assert metrics[1].conversation_message_id == "a-1"
    assert [metric.score for metric in metrics] == [0.65, 0.55, 1.0, 1.0]


def test_penalty_application_is_idempotent_for_score():
    transcript = [
        {"role": "agent", "content": "Which account?", "message_id": "a-1"},
        {"role": "user", "content": "Business.", "message_id": "u-1"},
        {"role": "agent", "content": "Which account?", "message_id": "a-2"},
    ]
    metric = MetricResult(name="Conversational Quality", score=1.0, passed=True, reason="", threshold=0.75)
    evaluator._apply_conversation_experience_penalties([metric], transcript)
    first_score = metric.score
    evaluator._apply_conversation_experience_penalties([metric], transcript)
    assert metric.score == first_score == 0.65


def test_different_progressive_questions_are_not_repetition():
    transcript = [
        {"role": "user", "content": "Help with my account."},
        {"role": "agent", "content": "Which account needs help?"},
        {"role": "user", "content": "Business."},
        {"role": "agent", "content": "Which transaction in the business account is disputed?"},
    ]
    metric = MetricResult(name="Context Retention", score=1.0, passed=True, reason="", threshold=0.75)
    evaluator._apply_conversation_experience_penalties([metric], transcript)
    assert metric.score == 1.0
