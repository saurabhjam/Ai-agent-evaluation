from __future__ import annotations

from app.calling.evaluation_adapter import CallingEvaluationAdapter
from app.evaluation_service import EvaluationResult
from app.executor import ExecutionResult
from app.schemas import AgentConfig, Persona, TestScenario


class FakeEvaluationService:
    def __init__(self):
        self.calls = []

    def evaluate(self, execution_result, scenario):
        self.calls.append((execution_result, scenario))
        return EvaluationResult(
            success=True,
            agent_id=execution_result.connection_id,
            agent_type=execution_result.agent_type,
            adapter=execution_result.adapter,
            scenario_id=scenario.scenario_id,
            session_id=execution_result.session_id,
            created_at="2026-10-01T10:00:00+00:00",
        )


def _scenario() -> TestScenario:
    return TestScenario(
        scenario_id="adapter-scenario",
        agent=AgentConfig(channel="calling", adapter="mock"),
        persona=Persona(
            name="Ava",
            goal="Book an appointment for tomorrow morning",
            tone="polite",
        ),
    )


def test_calling_evaluation_adapter_delegates_to_existing_service_shape():
    service = FakeEvaluationService()
    adapter = CallingEvaluationAdapter(evaluation_service=service)
    execution_result = ExecutionResult(
        success=True,
        connection_id="call-1",
        agent_type="calling",
        adapter="mock",
        session_id="session-1",
        transcript=[],
        started_at="2026-10-01T10:00:00+00:00",
        completed_at="2026-10-01T10:01:00+00:00",
    )

    result = adapter.evaluate(execution_result, _scenario())

    assert service.calls == [(execution_result, _scenario())]
    assert result.success is True
    assert result.agent_type == "calling"
    assert result.scenario_id == "adapter-scenario"
