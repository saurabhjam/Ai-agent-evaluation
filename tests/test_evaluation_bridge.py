from __future__ import annotations

from app.calling.evaluation_adapter import CallingEvaluationAdapter
from app.calling.evaluation_bridge import CallingEvaluationBridge
from app.calling.evaluation_runner import CallingEvaluationRuntimeRunner
from app.calling.execution_result import CallingExecutionResult, CallingExecutionStatus
from app.evaluation_service import EvaluationResult
from app.schemas import AgentConfig, Persona, TestScenario


class FakeEvaluationService:
    def __init__(self):
        self.execution_results = []
        self.scenarios = []

    def evaluate(self, execution_result, scenario):
        self.execution_results.append(execution_result)
        self.scenarios.append(scenario)
        if not execution_result.success:
            return EvaluationResult(
                success=False,
                agent_id=execution_result.connection_id,
                agent_type=execution_result.agent_type,
                adapter=execution_result.adapter,
                scenario_id=scenario.scenario_id,
                session_id=execution_result.session_id,
                error=f"Cannot evaluate: execution failed. Reason: {execution_result.error}",
                created_at="2026-10-01T10:00:00+00:00",
            )
        if not execution_result.transcript:
            return EvaluationResult(
                success=False,
                agent_id=execution_result.connection_id,
                agent_type=execution_result.agent_type,
                adapter=execution_result.adapter,
                scenario_id=scenario.scenario_id,
                session_id=execution_result.session_id,
                error="No conversation evidence was captured.",
                created_at="2026-10-01T10:00:00+00:00",
            )
        return EvaluationResult(
            success=True,
            agent_id=execution_result.connection_id,
            agent_type=execution_result.agent_type,
            adapter=execution_result.adapter,
            scenario_id=scenario.scenario_id,
            session_id=execution_result.session_id,
            overall_score=1.0,
            passed=True,
            created_at="2026-10-01T10:00:00+00:00",
        )


def _scenario() -> TestScenario:
    return TestScenario(
        scenario_id="bridge-scenario",
        agent=AgentConfig(channel="calling", adapter="mock"),
        persona=Persona(
            name="Ava",
            goal="Book an appointment for tomorrow morning",
            tone="polite",
        ),
        rag_context=["Use appointment policy."],
    )


def test_evaluation_bridge_converts_and_invokes_existing_service():
    scenario = _scenario()
    calling_result = CallingEvaluationRuntimeRunner().run(scenario)
    service = FakeEvaluationService()
    bridge = CallingEvaluationBridge(
        adapter=CallingEvaluationAdapter(evaluation_service=service)
    )

    evaluation_result = bridge.evaluate(calling_result, scenario)

    assert evaluation_result.success is True
    assert evaluation_result.agent_type == "calling"
    assert evaluation_result.scenario_id == "bridge-scenario"
    assert service.execution_results[0].transcript == calling_result.normalized_conversation.messages
    assert service.scenarios == [scenario]


def test_evaluation_bridge_builds_context_with_rag_support():
    scenario = _scenario()
    calling_result = CallingEvaluationRuntimeRunner().run(scenario)
    bridge = CallingEvaluationBridge()

    context = bridge.build_context(calling_result, scenario)

    assert context.scenario_id == "bridge-scenario"
    assert context.conversation == calling_result.normalized_conversation
    assert context.rag_context == ["Use appointment policy."]
    assert context.provider == "mock"


def test_evaluation_bridge_propagates_failed_calling_execution():
    scenario = _scenario()
    failed_result = CallingExecutionResult(
        status=CallingExecutionStatus.failed,
        error="provider failed",
    )
    service = FakeEvaluationService()
    bridge = CallingEvaluationBridge(
        adapter=CallingEvaluationAdapter(evaluation_service=service)
    )

    evaluation_result = bridge.evaluate(failed_result, scenario)

    assert evaluation_result.success is False
    assert "provider failed" in evaluation_result.error
    assert service.execution_results[0].success is False


def test_evaluation_bridge_missing_transcript_uses_existing_failure_path():
    scenario = _scenario()
    result = CallingExecutionResult(status=CallingExecutionStatus.completed)
    service = FakeEvaluationService()
    bridge = CallingEvaluationBridge(
        adapter=CallingEvaluationAdapter(evaluation_service=service)
    )

    evaluation_result = bridge.evaluate(result, scenario)

    assert evaluation_result.success is False
    assert evaluation_result.error == "No conversation evidence was captured."
    assert service.execution_results[0].transcript == []
