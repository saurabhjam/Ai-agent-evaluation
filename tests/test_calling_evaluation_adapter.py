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


def test_calling_pairwise_context_contains_role_evidence_without_rewriting_captured_dialogue():
    from app.models.conversation import ConversationMessage
    from app.evaluation_service import ConversationTurn

    class EchoService(FakeEvaluationService):
        def evaluate(self, execution, scenario):
            result = super().evaluate(execution, scenario)
            return result.model_copy(update={"conversation": [
                ConversationTurn(turn_index=i, speaker="agent" if m.role == "agent" else "user", message=m.content, metadata=m.metadata)
                for i, m in enumerate(execution.transcript)
            ]})

    messages = [
        ConversationMessage(role="agent", content="May I please have your full name?", turn_index=0),
        ConversationMessage(role="simulated_user", content="Okay.", turn_index=1),
        ConversationMessage(role="agent", content="Could you tell me your name?", turn_index=2),
    ]
    execution = ExecutionResult(success=True, connection_id="c", agent_type="calling", adapter="mock", transcript=messages, started_at="a", completed_at="b")
    service = EchoService()
    result = CallingEvaluationAdapter(evaluation_service=service).evaluate(execution, _scenario())
    annotated, configured = service.calls[0]
    assert '"justified_reasks":["name"]' in annotated.transcript[-1].content
    assert "Judge AGENT behavior separately" in annotated.transcript[1].content
    assert [m.message for m in result.conversation] == [m.content for m in messages]
    assert messages[1].content == "Okay."
    assert messages[1].metadata is None
    assert "confirmed transactions" in configured.persona.goal


def test_calling_rag_inputs_keep_existing_evaluation_path():
    from app.models.conversation import ConversationMessage, RAGEvidence

    messages = [ConversationMessage(role="agent", content="Answer", turn_index=0,
                                    rag_evidence=RAGEvidence(available=True, contexts=["reference"]))]
    execution = ExecutionResult(success=True, connection_id="c", agent_type="calling", adapter="mock", transcript=messages, started_at="a", completed_at="b")
    service = FakeEvaluationService()
    config = _scenario()
    CallingEvaluationAdapter(evaluation_service=service).evaluate(execution, config)
    assert service.calls[0] == (execution, config)
    assert messages[0].content == "Answer"
