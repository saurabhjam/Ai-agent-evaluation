from __future__ import annotations

from app.evaluation_service import EvaluationResult
from app.models.failure_analysis import FailureAnalysis


def test_failure_analysis_model_supports_enterprise_fields():
    failure = FailureAnalysis(
        metric_name="Goal Completion",
        status="FAIL",
        severity="high",
        reason="The agent did not complete the requested workflow.",
        expected="Appointment confirmation",
        actual="Conversation ended without confirmation",
        root_cause="Agent failed to collect the preferred time.",
        recommendation="Ask for missing scheduling fields before closing the flow.",
        conversation_turn=4,
        conversation_message_id="msg_004",
        evidence=["Agent: Anything else?"],
        technical_details={"metric_score": 0.2, "threshold": 0.7},
    )

    assert failure.failure_id
    assert failure.created_at
    assert failure.metric_name == "Goal Completion"
    assert failure.evidence == ["Agent: Anything else?"]
    assert failure.technical_details["threshold"] == 0.7


def test_evaluation_result_accepts_optional_failure_analysis():
    result = EvaluationResult(
        success=True,
        agent_id="conn_1",
        agent_type="chatbot",
        adapter="rest",
        scenario_id="scenario_1",
        overall_score=0.4,
        passed=False,
        created_at="2026-10-12T00:00:00+00:00",
        failure_analysis=[
            FailureAnalysis(
                metric_name="Persona",
                status="FAIL",
                severity="medium",
                reason="Tone did not match the persona.",
            )
        ],
    )

    assert result.failure_analysis is not None
    assert result.failure_analysis[0].metric_name == "Persona"


def test_evaluation_result_remains_backward_compatible_without_failure_analysis():
    result = EvaluationResult(
        success=True,
        agent_id="conn_1",
        agent_type="chatbot",
        adapter="rest",
        scenario_id="scenario_1",
        created_at="2026-10-12T00:00:00+00:00",
    )

    assert result.failure_analysis is None
    payload = result.model_dump()
    assert "failure_analysis" in payload
    assert payload["failure_analysis"] is None
