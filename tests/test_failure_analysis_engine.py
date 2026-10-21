from __future__ import annotations

from app.backend_validation.models import BackendValidationCheck, BackendValidationSummary
from app.evaluation_service import EvaluationService
from app.failure_analysis import FailureAnalysisEngine
from app.schemas import AgentConfig, MetricResult, Persona, TestScenario


def _scenario() -> TestScenario:
    return TestScenario(
        scenario_id="failure_analysis_scenario",
        agent=AgentConfig(channel="chatbot", adapter="fake"),
        persona=Persona(
            name="Test User",
            goal="Complete the requested customer support workflow.",
            tone="Polite",
        ),
        max_turns=3,
        pass_threshold=0.7,
    )


def _conversation():
    return [
        {"speaker": "user", "message": "I need help with my order.", "id": "msg_0"},
        {"speaker": "agent", "message": "I can help with billing.", "id": "msg_1"},
        {"speaker": "user", "message": "This is about a damaged item.", "id": "msg_2"},
    ]


def test_failed_intent_metric_generates_failure_analysis():
    engine = FailureAnalysisEngine()
    metric = MetricResult(
        name="Intent Detection",
        score=0.0,
        passed=False,
        reason="Detected billing intent instead of damage claim.",
        threshold=0.7,
        category="Intent Detection",
        turn_index=1,
    )

    result = engine.generate(metrics=[metric], conversation=_conversation(), scenario=_scenario())

    assert len(result) == 1
    assert result[0].metric_name == "Intent Detection"
    assert result[0].failure_id
    assert result[0].category == "Intent"
    assert result[0].source == "IntentEvaluator"
    assert result[0].created_at
    assert result[0].severity == "high"
    assert "intent" in result[0].root_cause.lower()
    assert result[0].conversation_turn == 1
    assert result[0].conversation_message_id == "msg_1"
    assert [item["label"] for item in result[0].conversation_snippet] == [
        "Previous Turn",
        "Failure Turn",
        "Next Turn",
    ]
    assert result[0].conversation_snippet[1]["conversation_message_id"] == "msg_1"
    assert result[0].business_impact
    assert result[0].evidence[0]["previous_turn"] == "Turn 0 - User: I need help with my order."
    assert result[0].evidence[0]["failed_turn"] == "Turn 1 - Agent: I can help with billing."
    assert "conversation_message_id" not in result[0].evidence[0]["failed_turn"]
    assert result[0].technical_details["conversation_message_refs"]["previous_turn"]["message_id"] == "msg_0"
    assert result[0].technical_details["conversation_message_refs"]["failure_turn"]["message_id"] == "msg_1"
    assert result[0].technical_details["conversation_message_refs"]["next_turn"]["message_id"] == "msg_2"
    assert "raw_conversation_snippet" in result[0].technical_details


def test_failure_analysis_consumes_metric_message_reference_directly():
    engine = FailureAnalysisEngine()
    metric = MetricResult(
        name="Intent Detection",
        score=0.0,
        passed=False,
        reason="Detected billing intent instead of damage claim.",
        category="Intent Detection",
        conversation_message_id="msg_1",
    )

    result = engine.generate(metrics=[metric], conversation=_conversation(), scenario=_scenario())

    assert result[0].conversation_turn == 1
    assert result[0].conversation_message_id == "msg_1"
    assert result[0].conversation_snippet[1]["message"] == "I can help with billing."


def test_failed_backend_validation_generates_failure_analysis():
    engine = FailureAnalysisEngine()
    backend = BackendValidationSummary(
        status="failed",
        passed=False,
        reason="Ticket was not created.",
        checks=[
            BackendValidationCheck(
                name="Verify Ticket",
                passed=False,
                reason="Status mismatch.",
                expected={"status": "OPEN"},
                actual={"status": "MISSING"},
                evidence={"endpoint": "/tickets/123", "status_code": 404},
            )
        ],
    )

    result = engine.generate(metrics=[], backend_validation=backend)

    assert len(result) == 1
    assert result[0].metric_name == "Backend Validation"
    assert result[0].category == "Backend Validation"
    assert result[0].source == "BackendValidationEngine"
    assert result[0].evidence[0]["title"] == "Verify Ticket"
    assert result[0].technical_details["checks"][0]["evidence"]["endpoint"] == "/tickets/123"
    assert "backend" in result[0].recommendation.lower()


def test_failed_ui_validation_generates_ui_recommendation():
    engine = FailureAnalysisEngine()
    metric = MetricResult(
        name="UI Validation",
        score=0.0,
        passed=False,
        reason="Upload control missing.",
        category="Workflow",
        turn_index=0,
    )

    result = engine.generate(metrics=[metric], conversation=_conversation())

    assert len(result) == 1
    assert "UI" in result[0].root_cause or "UI" in result[0].recommendation


def test_failed_workflow_metric_generates_workflow_analysis():
    engine = FailureAnalysisEngine()
    metric = MetricResult(
        name="Form Completion",
        score=0.0,
        passed=False,
        reason="Interaction failed or timed out.",
        category="Workflow",
        turn_index=2,
    )

    result = engine.generate(metrics=[metric], conversation=_conversation())

    assert len(result) == 1
    assert "workflow" in result[0].root_cause.lower()
    assert result[0].conversation_turn == 2


def test_passed_metrics_do_not_generate_failure_analysis():
    engine = FailureAnalysisEngine()
    metric = MetricResult(name="Goal Completion", score=1.0, passed=True, reason="Good")

    assert engine.generate(metrics=[metric]) == []


def test_missing_metric_reference_does_not_fabricate_conversation_evidence():
    engine = FailureAnalysisEngine()
    metric = MetricResult(name="Goal Completion", score=0.2, passed=False, reason="Bad")

    result = engine.generate(metrics=[metric], conversation=_conversation())

    assert result[0].conversation_turn is None
    assert result[0].conversation_message_id is None
    assert result[0].conversation_snippet is None


def test_missing_evidence_is_allowed():
    engine = FailureAnalysisEngine()
    metric = MetricResult(name="Response Validation", score=0.5, passed=False, reason="Incomplete")

    result = engine.generate(metrics=[metric])

    assert result[0].evidence == []
    assert result[0].technical_details["score"] == 0.5


def test_multiple_failures_are_all_returned():
    engine = FailureAnalysisEngine()
    metrics = [
        MetricResult(name="Goal Completion", score=0.0, passed=False, reason="No"),
        MetricResult(name="Safety Validation", score=0.0, passed=False, reason="Unsafe"),
    ]

    result = engine.generate(metrics=metrics)

    assert [item.metric_name for item in result] == ["Goal Completion", "Safety Validation"]


def test_multiple_failed_metrics_keep_distinct_conversation_references():
    engine = FailureAnalysisEngine()
    conversation = [
        {"speaker": "user", "message": "I need a maintenance request.", "id": "msg_0"},
        {"speaker": "agent", "message": "Do you want to search the property portfolio?", "id": "msg_1"},
        {"speaker": "user", "message": "The kitchen sink is leaking in unit 4B.", "id": "msg_2"},
        {"speaker": "agent", "message": "No matching records found.", "id": "msg_3"},
        {"speaker": "agent", "message": "I cannot create the maintenance ticket.", "id": "msg_4"},
    ]
    metrics = [
        MetricResult(
            name="Intent Understanding",
            score=0.1,
            passed=False,
            reason="The agent routed the maintenance request into portfolio search.",
            turn_index=1,
            conversation_message_id="msg_1",
        ),
        MetricResult(
            name="Answer Relevancy",
            score=0.2,
            passed=False,
            reason="The agent replied with no matching records instead of handling the leak.",
            turn_index=3,
            conversation_message_id="msg_3",
        ),
        MetricResult(
            name="Goal Completion",
            score=0.0,
            passed=False,
            reason="The maintenance ticket was not created.",
            turn_index=4,
            conversation_message_id="msg_4",
        ),
    ]

    result = engine.generate(metrics=metrics, conversation=conversation)

    assert [item.conversation_message_id for item in result] == ["msg_1", "msg_3", "msg_4"]
    assert [item.conversation_turn for item in result] == [1, 3, 4]
    assert len({item.evidence[0]["failed_turn"] for item in result}) == 3
    assert "portfolio search" in result[0].root_cause
    assert "No matching records" in result[1].actual
    assert "complete" in result[2].expected.lower()


def test_metric_reference_prefers_evaluator_reason_over_last_message():
    from app.evaluator import _metric_reference

    transcript = [
        {"role": "simulated_user", "content": "I need a maintenance request.", "turn_index": 0, "id": "msg_0"},
        {"role": "agent", "content": "Do you want to search the property portfolio?", "turn_index": 1, "id": "msg_1"},
        {"role": "simulated_user", "content": "The kitchen sink is leaking.", "turn_index": 2, "id": "msg_2"},
        {"role": "agent", "content": "No matching records found.", "turn_index": 3, "id": "msg_3"},
    ]

    reference = _metric_reference(
        transcript,
        "Intent Understanding",
        metric_reason="The agent routed the maintenance request into property portfolio search.",
    )

    assert reference == {"turn_index": 1, "conversation_message_id": "msg_1"}


def test_response_metric_reference_targets_failed_agent_response_not_user_question():
    from app.evaluator import _metric_reference

    transcript = [
        {"role": "simulated_user", "content": "Can you answer my maintenance question?", "turn_index": 0, "id": "msg_0"},
        {"role": "agent", "content": "No matching records found.", "turn_index": 1, "id": "msg_1"},
        {"role": "simulated_user", "content": "That did not answer my question.", "turn_index": 2, "id": "msg_2"},
        {"role": "agent", "content": "Please start over.", "turn_index": 3, "id": "msg_3"},
    ]

    reference = _metric_reference(
        transcript,
        "Answer Relevancy",
        metric_reason='The agent failed to answer "Can you answer my maintenance question?" and replied "No matching records found."',
    )

    assert reference == {"turn_index": 1, "conversation_message_id": "msg_1"}


def test_failure_snippet_keeps_distinct_previous_failure_next_message_ids():
    engine = FailureAnalysisEngine()
    conversation = [
        {"speaker": "user", "message": "Can you answer my maintenance question?", "id": "msg_0"},
        {"speaker": "agent", "message": "No matching records found.", "id": "msg_1"},
        {"speaker": "user", "message": "That did not answer my question.", "id": "msg_2"},
    ]
    metric = MetricResult(
        name="Answer Relevancy",
        score=0.1,
        passed=False,
        reason="The agent gave an unrelated answer.",
        turn_index=1,
        conversation_message_id="msg_1",
    )

    result = engine.generate(metrics=[metric], conversation=conversation)[0]
    refs = result.technical_details["conversation_message_refs"]

    assert result.conversation_message_id == "msg_1"
    assert result.evidence[0]["previous_turn"].startswith("Turn 0 - User")
    assert result.evidence[0]["failed_turn"].startswith("Turn 1 - Agent")
    assert result.evidence[0]["next_turn"].startswith("Turn 2 - User")
    assert result.actual == 'Agent response: "No matching records found."'
    assert result.failure_summary == "The response did not answer the user's question and shifted to unrelated information."
    assert result.reason not in result.actual
    assert result.root_cause != result.actual
    assert result.evidence[0]["why_this_proves_failure"] != result.root_cause
    assert {refs["previous_turn"]["message_id"], refs["failure_turn"]["message_id"], refs["next_turn"]["message_id"]} == {
        "msg_0",
        "msg_1",
        "msg_2",
    }


def test_empty_evaluation_returns_no_failure_analysis():
    assert FailureAnalysisEngine().generate(metrics=[], voice_metrics=[]) == []


def test_failure_analysis_content_sections_are_not_duplicated():
    engine = FailureAnalysisEngine()
    metric = MetricResult(
        name="Multi-turn Consistency",
        score=0.1,
        passed=False,
        reason="The agent restarted the workflow after collecting the user's unit.",
        turn_index=1,
        conversation_message_id="msg_1",
    )

    result = engine.generate(metrics=[metric], conversation=_conversation())[0]
    rendered_sections = [
        result.failure_summary,
        result.business_impact,
        result.root_cause,
        result.evidence[0]["why_this_proves_failure"],
        result.recommendation,
    ]

    assert len(rendered_sections) == len(set(rendered_sections))
    assert "turn" not in result.failure_summary.lower()
    assert "score" not in result.failure_summary.lower()
    assert "multi-turn consistency" not in result.failure_summary.lower()
    assert result.failure_summary != result.root_cause
    assert result.root_cause != result.recommendation
    assert result.evidence[0]["why_this_proves_failure"] != result.failure_summary


def test_metric_specific_failure_wording_for_supported_categories():
    engine = FailureAnalysisEngine()
    names = [
        "Intent Detection",
        "Goal Completion",
        "Response Quality",
        "Answer Relevancy",
        "Context Retention",
        "Multi-turn Consistency",
        "Conversation Quality",
        "Workflow Validation",
        "Backend Validation",
        "UI Validation",
        "Safety",
        "RAG",
        "Hallucination",
        "Groundedness",
        "Completeness",
        "Tone",
        "Persona",
    ]
    metrics = [
        MetricResult(name=name, score=0.1, passed=False, reason=f"{name} failed.", turn_index=1)
        for name in names
    ]

    results = engine.generate(metrics=metrics, conversation=_conversation())
    summaries = {result.metric_name: result.failure_summary for result in results}
    recommendations = {result.metric_name: result.recommendation for result in results}

    assert len(results) == len(names)
    assert "wrong workflow" in summaries["Intent Detection"]
    assert "expected completed outcome" in summaries["Goal Completion"]
    assert "low-quality response" in summaries["Response Quality"]
    assert "did not answer" in summaries["Answer Relevancy"]
    assert "already established" in summaries["Context Retention"]
    assert "unnecessarily restarted" in summaries["Multi-turn Consistency"]
    assert "difficult to follow" in summaries["Conversation Quality"]
    assert "workflow step" in summaries["Workflow Validation"]
    assert "system state" in summaries["Backend Validation"]
    assert "user-interface interaction" in summaries["UI Validation"]
    assert "safety" in summaries["Safety"].lower()
    assert "retrieved knowledge" in summaries["RAG"]
    assert "unsupported claim" in summaries["Hallucination"]
    assert "not grounded" in summaries["Groundedness"]
    assert "expected completed outcome" in summaries["Completeness"]
    assert "tone" in summaries["Tone"].lower()
    assert "persona" in summaries["Persona"].lower()
    assert recommendations["Intent Detection"] != recommendations["Workflow Validation"]


def test_evaluation_service_populates_failure_analysis_without_changing_score(monkeypatch):
    from app.executor import ExecutionResult
    import app.evaluation_service as evaluation_service

    monkeypatch.setattr(
        evaluation_service,
        "evaluate_transcript",
        lambda **kwargs: [
            MetricResult(name="Goal Completion", score=0.2, passed=False, reason="Incomplete", threshold=0.7)
        ],
    )
    monkeypatch.setattr(evaluation_service, "run_workflow_metrics", lambda transcript: [])

    service = EvaluationService()
    result = service.evaluate(
        ExecutionResult(
            success=True,
            connection_id="conn_1",
            agent_type="chatbot",
            adapter="rest",
            transcript=[{"role": "assistant", "content": "I cannot help."}],
            started_at="start",
            completed_at="end",
        ),
        _scenario(),
    )

    assert result.overall_score == 0.2
    assert result.passed is False
    assert result.failure_analysis
    assert result.failure_analysis[0].metric_name == "Goal Completion"
    assert result.conversation[0].conversation_message_id == "ef-message-0"
    assert result.conversation[0].turn_index == 0
    # The evaluator did not identify a failing message, so failure analysis must
    # not attribute the failure to an arbitrary transcript item.
    assert result.failure_analysis[0].conversation_message_id is None
    assert result.failure_analysis[0].conversation_turn is None
