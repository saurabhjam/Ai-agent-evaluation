from __future__ import annotations

import pytest

from app.calling.calling_result_converter import CallingResultConverter
from app.calling.evaluation_runner import CallingEvaluationRuntimeRunner
from app.calling.execution_result import CallingExecutionResult, CallingExecutionStatus
from app.models.conversation import ConversationMessage
from app.schemas import AgentConfig, Persona, TestScenario


def _scenario() -> TestScenario:
    return TestScenario(
        scenario_id="converter-scenario",
        agent=AgentConfig(channel="calling", adapter="mock"),
        persona=Persona(
            name="Ava",
            goal="Book an appointment for tomorrow morning",
            tone="polite",
        ),
        rag_context=["Use appointment policy."],
    )


def test_calling_result_converter_builds_existing_execution_result():
    calling_result = CallingEvaluationRuntimeRunner().run(_scenario())

    execution_result = CallingResultConverter().to_execution_result(calling_result)

    assert execution_result.success is True
    assert execution_result.agent_type == "calling"
    assert execution_result.adapter == "mock"
    assert execution_result.session_id == calling_result.call_session.session_id
    assert execution_result.transcript == calling_result.normalized_conversation.messages
    assert execution_result.voice_conversation is None


def test_calling_result_converter_builds_evaluation_context():
    scenario = _scenario()
    calling_result = CallingEvaluationRuntimeRunner().run(scenario)

    context = CallingResultConverter().to_evaluation_context(
        calling_result,
        scenario_id=scenario.scenario_id,
    )

    assert context.scenario_id == "converter-scenario"
    assert context.run_id == calling_result.normalized_conversation.run_id
    assert context.provider == "mock"
    assert context.call_id == calling_result.call_session.provider_call_id
    assert context.conversation == calling_result.normalized_conversation
    assert context.artifacts == calling_result.artifacts
    assert context.rag_context == calling_result.normalized_conversation.retrieval_context


def test_calling_result_converter_rejects_missing_normalized_conversation_context():
    result = CallingExecutionResult(status=CallingExecutionStatus.failed, error="missing")

    with pytest.raises(ValueError, match="missing normalized conversation"):
        CallingResultConverter().to_evaluation_context(result, scenario_id="missing")


def test_calling_result_converter_excludes_system_prompt_from_evaluator_transcript():
    calling_result = CallingEvaluationRuntimeRunner().run(_scenario())
    conversation = calling_result.normalized_conversation
    conversation = conversation.model_copy(update={
        "messages": [
            ConversationMessage(role="system", content="Internal provider prompt", turn_index=-1),
            *conversation.messages,
        ]
    })

    execution_result = CallingResultConverter().to_execution_result(
        calling_result.model_copy(update={"normalized_conversation": conversation})
    )

    assert all(message.role != "system" for message in execution_result.transcript)
    assert all(message.content != "Internal provider prompt" for message in execution_result.transcript)
