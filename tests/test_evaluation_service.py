"""
Tests for EvaluationService.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from app.backend_validation import BackendValidationEngine
from app.evaluation_service import EvaluationService
from app.executor import ExecutionResult
from app.schemas import TestScenario, Persona, AgentConfig, MetricResult
from app.models.connection import AgentType
from app.models.conversation import ConversationMessage, RAGEvidence, ToolCallInfo


@pytest.fixture
def mock_scenario():
    return TestScenario(
        scenario_id="test_scenario_01",
        agent=AgentConfig(channel="chatbot", adapter="fake"),
        persona=Persona(name="Test User", goal="Testing goal length requirement", tone="Test"),
        max_turns=3,
        pass_threshold=0.5
    )


@patch("app.evaluation_service.evaluate_transcript")
def test_chatbot_evaluation(mock_eval, mock_scenario):
    mock_eval.return_value = [
        MetricResult(name="Goal Completion", score=0.8, reason="Good", passed=True)
    ]
    
    exec_res = ExecutionResult(
        success=True,
        connection_id="conn_1",
        agent_type=AgentType.chatbot.value,
        adapter="rest",
        transcript=[{"role": "user", "content": "hello"}],
        started_at="start",
        completed_at="end"
    )
    
    service = EvaluationService()
    result = service.evaluate(exec_res, mock_scenario)
    
    assert result.success
    assert result.agent_type == "chatbot"
    assert result.overall_score == 0.8
    assert result.passed
    assert result.voice_metrics is None
    
    mock_eval.assert_called_once()
    assert mock_eval.call_args[1]["transcript"] == exec_res.transcript
    assert mock_eval.call_args[1]["rag_context"] is None
    assert mock_eval.call_args[1]["rag_evidence_by_turn"] is None
    assert result.rag_evaluation.status == "not_evaluated"


@patch("app.evaluation_service.evaluate_transcript")
@patch("app.evaluation_service.run_voice_metrics")
def test_voice_evaluation(mock_voice_metrics, mock_eval, mock_scenario):
    mock_eval.return_value = [
        MetricResult(name="Goal Completion", score=0.6, reason="Ok", passed=True)
    ]
    mock_voice_metrics.return_value = [
        MetricResult(name="Latency", score=1.0, reason="Fast", passed=True)
    ]
    
    exec_res = ExecutionResult(
        success=True,
        connection_id="conn_2",
        agent_type=AgentType.voice.value,
        adapter="livekit",
        transcript=[{"role": "user", "content": "hi"}],
        voice_conversation=MagicMock(),
        started_at="start",
        completed_at="end"
    )
    
    service = EvaluationService()
    result = service.evaluate(exec_res, mock_scenario)
    
    assert result.success
    assert result.agent_type == "voice"
    assert result.overall_score == 0.6  # Only base metrics count towards overall_score in this POC
    assert result.passed
    assert result.voice_metrics is not None
    assert len(result.voice_metrics) == 1
    
    mock_eval.assert_called_once()
    mock_voice_metrics.assert_called_once()


def test_failed_execution_returns_failed_evaluation(mock_scenario):
    exec_res = ExecutionResult(
        success=False,
        connection_id="conn_3",
        agent_type="chatbot",
        adapter="fake",
        error="Network error",
        started_at="start",
        completed_at="end"
    )
    
    service = EvaluationService()
    result = service.evaluate(exec_res, mock_scenario)
    
    assert not result.success
    assert "Network error" in result.error


def test_empty_chatbot_transcript_returns_failed_evaluation(mock_scenario):
    exec_res = ExecutionResult(
        success=True,
        connection_id="conn_1",
        agent_type="chatbot",
        adapter="rest",
        transcript=[],
        started_at="start",
        completed_at="end"
    )
    
    service = EvaluationService()
    result = service.evaluate(exec_res, mock_scenario)
    
    assert not result.success
    assert "No conversation evidence" in result.error


def test_empty_voice_transcript_returns_failed_evaluation(mock_scenario):
    exec_res = ExecutionResult(
        success=True,
        connection_id="conn_2",
        agent_type="voice",
        adapter="livekit",
        transcript=[],
        voice_conversation=MagicMock(),
        started_at="start",
        completed_at="end"
    )
    
    service = EvaluationService()
    result = service.evaluate(exec_res, mock_scenario)
    
    assert not result.success
    assert "No conversation evidence" in result.error

class TestBackendValidationEngine(BackendValidationEngine):
    def validate(self, transcript, scenario):
        result = super().validate(transcript, scenario)
        return result.model_copy(update={"status": "validated", "passed": True, "reason": "DB updated"})


@patch("app.evaluation_service.evaluate_transcript")
def test_backend_validation_is_stored_separately(mock_eval, mock_scenario):
    mock_eval.return_value = [
        MetricResult(name="Goal Completion", score=1.0, reason="Good", passed=True)
    ]

    exec_res = ExecutionResult(
        success=True,
        connection_id="conn_1",
        agent_type="chatbot",
        adapter="rest",
        transcript=[{"role": "user", "content": "hi"}],
        started_at="start",
        completed_at="end"
    )
    
    service = EvaluationService(backend_validation_engine=TestBackendValidationEngine())
    result = service.evaluate(exec_res, mock_scenario)
    
    assert result.success
    assert len(result.metrics) == 1
    assert result.metrics[0].name == "Goal Completion"
    assert result.backend_validation.status == "validated"
    assert result.backend_validation.reason == "DB updated"


@patch("app.evaluation_service.evaluate_transcript")
def test_evaluation_failure_is_caught(mock_eval, mock_scenario):
    mock_eval.side_effect = Exception("DeepEval crashed")
    
    exec_res = ExecutionResult(
        success=True,
        connection_id="conn_1",
        agent_type="chatbot",
        adapter="rest",
        transcript=[{"role": "user", "content": "hi"}],
        started_at="start",
        completed_at="end"
    )
    
    service = EvaluationService()
    result = service.evaluate(exec_res, mock_scenario)
    
    assert not result.success
    assert "DeepEval crashed" in result.error


@patch("app.evaluation_service.evaluate_transcript")
def test_evaluation_preserves_rich_conversation_presentation_data(mock_eval, mock_scenario):
    mock_eval.return_value = [
        MetricResult(name="Goal Completion", score=1.0, reason="Good", passed=True)
    ]

    exec_res = ExecutionResult(
        success=True,
        connection_id="conn_1",
        agent_type="chatbot",
        adapter="browser",
        transcript=[
            ConversationMessage(
                role="simulated_user",
                content="Upload Image\ndamage.jpg",
                turn_index=0,
                attachments=["test-data/damage.jpg"],
                metadata={
                    "action": "upload_image",
                    "file_name": "damage.jpg",
                    "mime_type": "image/jpeg",
                    "size": 1234,
                },
            ),
            ConversationMessage(
                role="agent",
                content="Choose an appointment",
                turn_index=1,
                metadata={
                    "components": [
                        {"type": "button", "label": "Book Appointment"},
                        {"type": "table", "headers": ["Slot"], "rows": [["14:30"]]},
                    ]
                },
                tool_calls=[
                    ToolCallInfo(
                        tool_name="availability_lookup",
                        tool_input={"city": "Pune"},
                        tool_output={"slots": ["14:30"]},
                    )
                ],
            ),
        ],
        started_at="start",
        completed_at="end",
    )

    result = EvaluationService().evaluate(exec_res, mock_scenario)

    assert result.success is True
    assert result.conversation[0].attachments == ["test-data/damage.jpg"]
    assert result.conversation[0].metadata["action"] == "upload_image"
    assert result.conversation[0].components is None
    assert result.conversation[1].components[0]["type"] == "button"
    assert result.conversation[1].components[1]["type"] == "table"
    assert result.conversation[1].tool_calls[0]["tool_name"] == "availability_lookup"


@patch("app.evaluation_service.evaluate_transcript")
def test_evaluation_generates_unique_message_ids_when_adapter_reuses_turn_index(mock_eval, mock_scenario):
    mock_eval.return_value = [
        MetricResult(
            name="Answer Relevancy",
            score=0.2,
            reason="The agent response did not answer the user question.",
            passed=False,
            turn_index=1,
            conversation_message_id="ef-message-1",
        )
    ]
    exec_res = ExecutionResult(
        success=True,
        connection_id="conn_1",
        agent_type="chatbot",
        adapter="rest",
        transcript=[
            ConversationMessage(role="simulated_user", content="Question", turn_index=9),
            ConversationMessage(role="agent", content="Wrong answer", turn_index=9),
            ConversationMessage(role="simulated_user", content="Follow up", turn_index=10),
        ],
        started_at="start",
        completed_at="end",
    )

    result = EvaluationService().evaluate(exec_res, mock_scenario)

    assert [turn.turn_index for turn in result.conversation] == [0, 1, 2]
    assert [turn.conversation_message_id for turn in result.conversation] == [
        "ef-message-0",
        "ef-message-1",
        "ef-message-2",
    ]
    assert result.conversation[0].metadata["original_turn_index"] == 9
    assert result.conversation[1].metadata["original_turn_index"] == 9
    failure = result.failure_analysis[0]
    assert failure.conversation_message_id == "ef-message-1"
    refs = failure.technical_details["conversation_message_refs"]
    assert refs["previous_turn"]["message_id"] == "ef-message-0"
    assert refs["failure_turn"]["message_id"] == "ef-message-1"
    assert refs["next_turn"]["message_id"] == "ef-message-2"


@patch("app.evaluation_service.evaluate_transcript")
def test_agent_rag_evidence_has_priority_over_scenario_context(mock_eval, mock_scenario):
    mock_eval.return_value = [
        MetricResult(name="Faithfulness", score=1.0, reason="Grounded", passed=True)
    ]
    scenario = mock_scenario.model_copy(update={"rag_context": ["Static reference context"]})
    exec_res = ExecutionResult(
        success=True,
        connection_id="conn_1",
        agent_type="chatbot",
        adapter="rest",
        transcript=[
            ConversationMessage(role="simulated_user", content="What is the refund policy?", turn_index=0),
            ConversationMessage(
                role="agent",
                content="Refunds are allowed within 30 days.",
                turn_index=1,
                rag_evidence=RAGEvidence(
                    available=True,
                    source="agent_retrieval",
                    contexts=["Customers can return products within 30 days."],
                ),
            ),
        ],
        started_at="start",
        completed_at="end",
    )

    result = EvaluationService().evaluate(exec_res, scenario)

    assert result.success is True
    assert result.rag_evaluation.status == "evaluated"
    assert result.rag_evaluation.evidence_source == "agent_retrieval"
    assert result.rag_evaluation.context_count == 1
    assert result.conversation[1].rag.contexts == ["Customers can return products within 30 days."]
    assert mock_eval.call_args[1]["rag_context"] is None
    assert mock_eval.call_args[1]["rag_evidence_by_turn"][0]["input"] == "What is the refund policy?"
    assert mock_eval.call_args[1]["rag_evidence_by_turn"][0]["contexts"] == ["Customers can return products within 30 days."]


@patch("app.evaluation_service.evaluate_transcript")
def test_scenario_rag_context_is_reference_context_fallback(mock_eval, mock_scenario):
    mock_eval.return_value = [
        MetricResult(name="Faithfulness", score=1.0, reason="Grounded", passed=True)
    ]
    scenario = mock_scenario.model_copy(update={"rag_context": ["Reference refund policy"]})
    exec_res = ExecutionResult(
        success=True,
        connection_id="conn_1",
        agent_type="chatbot",
        adapter="rest",
        transcript=[
            ConversationMessage(role="simulated_user", content="What is the refund policy?", turn_index=0),
            ConversationMessage(role="agent", content="Refunds are allowed.", turn_index=1),
        ],
        started_at="start",
        completed_at="end",
    )

    result = EvaluationService().evaluate(exec_res, scenario)

    assert result.success is True
    assert result.rag_evaluation.status == "evaluated"
    assert result.rag_evaluation.evidence_source == "reference_context"
    assert result.rag_evaluation.context_count == 1
    assert mock_eval.call_args[1]["rag_context"] == ["Reference refund policy"]
    assert mock_eval.call_args[1]["rag_evidence_by_turn"] is None


@patch("app.evaluation_service.evaluate_transcript")
def test_multiple_turn_rag_evidence_remains_turn_scoped(mock_eval, mock_scenario):
    mock_eval.return_value = [
        MetricResult(name="Faithfulness", score=1.0, reason="Grounded", passed=True)
    ]
    exec_res = ExecutionResult(
        success=True,
        connection_id="conn_1",
        agent_type="chatbot",
        adapter="rest",
        transcript=[
            ConversationMessage(role="simulated_user", content="Question A", turn_index=0),
            ConversationMessage(
                role="agent",
                content="Answer A",
                turn_index=1,
                rag_evidence=RAGEvidence(available=True, source="agent_retrieval", contexts=["Context A"]),
            ),
            ConversationMessage(role="simulated_user", content="Question B", turn_index=2),
            ConversationMessage(
                role="agent",
                content="Answer B",
                turn_index=3,
                rag_evidence=RAGEvidence(available=True, source="agent_retrieval", contexts=["Context B"]),
            ),
        ],
        started_at="start",
        completed_at="end",
    )

    result = EvaluationService().evaluate(exec_res, mock_scenario)

    turn_evidence = mock_eval.call_args[1]["rag_evidence_by_turn"]
    assert result.rag_evaluation.evidence_source == "agent_retrieval"
    assert result.rag_evaluation.context_count == 2
    assert turn_evidence[0]["input"] == "Question A"
    assert turn_evidence[0]["contexts"] == ["Context A"]
    assert turn_evidence[1]["input"] == "Question B"
    assert turn_evidence[1]["contexts"] == ["Context B"]


@patch("app.evaluation_service.evaluate_transcript")
def test_rag_category_has_equal_weight_for_one_turn(mock_eval, mock_scenario):
    mock_eval.return_value = [
        MetricResult(name="Goal Completion", score=0.8, reason="Good", passed=True, category="base"),
        MetricResult(name="Persona and Tone Adherence", score=0.8, reason="Good", passed=True, category="base"),
        MetricResult(name="Conversational Quality", score=0.8, reason="Good", passed=True, category="base"),
        MetricResult(name="Faithfulness", score=0.6, reason="Grounded", passed=True, category="rag", evidence_source="agent_retrieval", turn_index=1),
        MetricResult(name="Answer Relevancy", score=0.6, reason="Relevant", passed=True, category="rag", evidence_source="agent_retrieval", turn_index=1),
        MetricResult(name="Hallucination", score=0.6, reason="No issue", passed=True, category="rag", evidence_source="agent_retrieval", turn_index=1),
    ]
    exec_res = ExecutionResult(
        success=True,
        connection_id="conn_1",
        agent_type="chatbot",
        adapter="rest",
        transcript=[
            ConversationMessage(role="simulated_user", content="Question", turn_index=0),
            ConversationMessage(
                role="agent",
                content="Answer",
                turn_index=1,
                rag_evidence=RAGEvidence(available=True, source="agent_retrieval", contexts=["Context"]),
            ),
        ],
        started_at="start",
        completed_at="end",
    )

    result = EvaluationService().evaluate(exec_res, mock_scenario)

    assert result.overall_score == 0.7
    assert result.rag_evaluation.rag_score == 0.6


@patch("app.evaluation_service.evaluate_transcript")
def test_rag_category_has_equal_weight_for_five_turns(mock_eval, mock_scenario):
    metrics = [
        MetricResult(name="Goal Completion", score=0.8, reason="Good", passed=True, category="base"),
        MetricResult(name="Persona and Tone Adherence", score=0.8, reason="Good", passed=True, category="base"),
        MetricResult(name="Conversational Quality", score=0.8, reason="Good", passed=True, category="base"),
    ]
    for turn in range(1, 6):
        metrics.extend([
            MetricResult(name=f"Faithfulness (Turn {turn})", score=0.6, reason="Grounded", passed=True, category="rag", evidence_source="agent_retrieval", turn_index=turn),
            MetricResult(name=f"Answer Relevancy (Turn {turn})", score=0.6, reason="Relevant", passed=True, category="rag", evidence_source="agent_retrieval", turn_index=turn),
            MetricResult(name=f"Hallucination (Turn {turn})", score=0.6, reason="No issue", passed=True, category="rag", evidence_source="agent_retrieval", turn_index=turn),
        ])
    mock_eval.return_value = metrics
    transcript = []
    for turn in range(1, 6):
        transcript.append(ConversationMessage(role="simulated_user", content=f"Question {turn}", turn_index=(turn * 2) - 2))
        transcript.append(
            ConversationMessage(
                role="agent",
                content=f"Answer {turn}",
                turn_index=(turn * 2) - 1,
                rag_evidence=RAGEvidence(available=True, source="agent_retrieval", contexts=[f"Context {turn}"]),
            )
        )
    exec_res = ExecutionResult(
        success=True,
        connection_id="conn_1",
        agent_type="chatbot",
        adapter="rest",
        transcript=transcript,
        started_at="start",
        completed_at="end",
    )

    result = EvaluationService().evaluate(exec_res, mock_scenario)

    assert result.overall_score == 0.7
    assert result.rag_evaluation.rag_score == 0.6
    assert len(result.metrics) == 18
