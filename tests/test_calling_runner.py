from __future__ import annotations

from app.calling.config import CallingProviderConfig
from app.calling.evaluation_runner import CallingEvaluationRuntimeRunner
from app.calling.execution_result import CallingExecutionStatus
from app.calling.models import CallStatus
from app.schemas import AgentConfig, Persona, TestScenario


def _scenario() -> TestScenario:
    return TestScenario(
        scenario_id="calling-runner",
        agent=AgentConfig(channel="calling", adapter="mock"),
        persona=Persona(
            name="Ava",
            goal="Book an appointment for tomorrow morning",
            tone="polite",
        ),
    )


def test_calling_runtime_runner_returns_execution_result():
    runner = CallingEvaluationRuntimeRunner()

    result = runner.run(
        _scenario(),
        provider_config=CallingProviderConfig(provider_name="mock"),
    )

    assert result.status == CallingExecutionStatus.completed
    assert result.call_session.status == CallStatus.completed
    assert result.conversation_evidence.provider_name == "mock"
    assert result.normalized_conversation.channel == "calling"
    assert result.execution_metadata["scenario_id"] == "calling-runner"


def test_calling_runtime_runner_does_not_include_evaluation_scores():
    result = CallingEvaluationRuntimeRunner().run(_scenario())

    assert not hasattr(result, "metrics")
    assert not hasattr(result, "overall_score")
    assert result.normalized_conversation.messages
