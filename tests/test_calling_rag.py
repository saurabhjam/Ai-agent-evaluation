from unittest.mock import patch

from app.calling.calling_result_converter import CallingResultConverter
from app.calling.config import CallingProviderConfig
from app.calling.evaluation_runner import CallingEvaluationRuntimeRunner
from app.calling.execution_result import CallingExecutionResult, CallingExecutionStatus
from app.calling.models import (
    CallDirection,
    CallProvider,
    CallSession,
    CallStatus,
    CallTranscriptTurn,
    NormalizedCallTranscript,
    TranscriptSpeaker,
)
from app.calling.normalizer import call_transcript_to_normalized_conversation
from app.evaluation_service import EvaluationService
from app.schemas import AgentConfig, Persona, TestScenario


def _rag_config(**overrides):
    config = {
        "enabled": True,
        "context_path": "retrieved_chunks[*].content",
        "citation_path": "sources[*]",
        "source_type": "agent_retrieval",
    }
    config.update(overrides)
    return config


def _transcript(*turns: CallTranscriptTurn) -> NormalizedCallTranscript:
    return NormalizedCallTranscript(session_id="call-session-1", run_id="run-1", turns=list(turns), source="test")


def _agent_turn(text="Answer", metadata=None, turn_index=0) -> CallTranscriptTurn:
    return CallTranscriptTurn(
        speaker=TranscriptSpeaker.agent,
        text=text,
        turn_index=turn_index,
        metadata=metadata or {},
    )


def _scenario() -> TestScenario:
    return TestScenario(
        scenario_id="calling-rag",
        agent=AgentConfig(channel="calling", adapter="mock"),
        persona=Persona(name="Ava", goal="Ask a policy question", tone="neutral"),
        rag_context=["Scenario fallback"],
    )


def test_calling_agent_turn_with_inline_retrieval_context():
    transcript = _transcript(
        _agent_turn(metadata={"retrieved_chunks": [{"content": "Refunds are allowed within 30 days."}]})
    )

    normalized = call_transcript_to_normalized_conversation(transcript, rag_config=_rag_config())

    assert normalized.messages[0].rag_evidence.contexts == ["Refunds are allowed within 30 days."]


def test_calling_rag_multiple_context_snippets():
    transcript = _transcript(
        _agent_turn(metadata={"retrieved_chunks": [{"content": "Chunk A"}, {"content": "Chunk B"}]})
    )

    normalized = call_transcript_to_normalized_conversation(transcript, rag_config=_rag_config())

    assert normalized.messages[0].rag_evidence.contexts == ["Chunk A", "Chunk B"]


def test_calling_rag_nested_metadata_path():
    transcript = _transcript(
        _agent_turn(metadata={"trace": {"retrieval": {"chunks": [{"text": "Nested chunk"}]}}})
    )

    normalized = call_transcript_to_normalized_conversation(
        transcript,
        rag_config=_rag_config(context_path="trace.retrieval.chunks[*].text"),
    )

    assert normalized.messages[0].rag_evidence.contexts == ["Nested chunk"]


def test_calling_rag_citation_and_textual_context():
    transcript = _transcript(
        _agent_turn(
            metadata={
                "retrieved_chunks": [{"content": "Warranty lasts one year."}],
                "sources": [{"title": "Warranty Policy", "url": "https://example.test/warranty"}],
            }
        )
    )

    normalized = call_transcript_to_normalized_conversation(transcript, rag_config=_rag_config())

    evidence = normalized.messages[0].rag_evidence
    assert evidence.contexts == ["Warranty lasts one year."]
    assert evidence.citations == [{"title": "Warranty Policy", "url": "https://example.test/warranty"}]


def test_calling_rag_citation_only_does_not_fabricate_context():
    transcript = _transcript(
        _agent_turn(metadata={"sources": [{"title": "Refund Policy", "url": "https://example.test/refunds"}]})
    )

    normalized = call_transcript_to_normalized_conversation(transcript, rag_config=_rag_config())

    evidence = normalized.messages[0].rag_evidence
    assert evidence.contexts == []
    assert evidence.citations == [{"title": "Refund Policy", "url": "https://example.test/refunds"}]


def test_calling_rag_no_config_preserves_existing_behavior():
    transcript = _transcript(
        _agent_turn(metadata={"retrieved_chunks": [{"content": "Should not be extracted"}]})
    )

    normalized = call_transcript_to_normalized_conversation(transcript)

    assert normalized.messages[0].rag_evidence is None
    assert normalized.messages[0].metadata["retrieved_chunks"] == [{"content": "Should not be extracted"}]


def test_calling_rag_missing_context_path_has_no_evidence():
    normalized = call_transcript_to_normalized_conversation(
        _transcript(_agent_turn(metadata={"other": []})),
        rag_config=_rag_config(),
    )

    assert normalized.messages[0].rag_evidence is None


def test_calling_rag_empty_context_has_no_evidence():
    normalized = call_transcript_to_normalized_conversation(
        _transcript(_agent_turn(metadata={"retrieved_chunks": [{"content": "  "}]})),
        rag_config=_rag_config(),
    )

    assert normalized.messages[0].rag_evidence is None


def test_calling_rag_malformed_context_has_no_evidence():
    normalized = call_transcript_to_normalized_conversation(
        _transcript(_agent_turn(metadata={"retrieved_chunks": [{"value": {"nested": True}}]})),
        rag_config=_rag_config(),
    )

    assert normalized.messages[0].rag_evidence is None


def test_calling_rag_extraction_exception_does_not_break_normalization():
    with patch("app.calling.normalizer.extract_rag_evidence", side_effect=RuntimeError("boom")):
        normalized = call_transcript_to_normalized_conversation(
            _transcript(_agent_turn(metadata={"retrieved_chunks": [{"content": "Context"}]})),
            rag_config=_rag_config(),
        )

    assert normalized.messages[0].content == "Answer"
    assert normalized.messages[0].rag_evidence is None


def test_calling_rag_two_agent_turns_retain_independent_evidence():
    normalized = call_transcript_to_normalized_conversation(
        _transcript(
            _agent_turn("Answer 1", {"retrieved_chunks": [{"content": "C1"}]}, 0),
            _agent_turn("Answer 2", {"retrieved_chunks": [{"content": "C2"}]}, 1),
        ),
        rag_config=_rag_config(),
    )

    assert normalized.messages[0].rag_evidence.contexts == ["C1"]
    assert normalized.messages[1].rag_evidence.contexts == ["C2"]


def test_calling_rag_turn_one_evidence_does_not_leak_into_turn_two():
    normalized = call_transcript_to_normalized_conversation(
        _transcript(
            _agent_turn("Answer 1", {"retrieved_chunks": [{"content": "C1"}]}, 0),
            _agent_turn("Answer 2", {"unrelated": "metadata"}, 1),
        ),
        rag_config=_rag_config(),
    )

    assert normalized.messages[0].rag_evidence.contexts == ["C1"]
    assert normalized.messages[1].rag_evidence is None


def test_calling_rag_survives_calling_result_converter_to_execution_result():
    session = CallSession(
        session_id="session-1",
        run_id="run-1",
        direction=CallDirection.outbound,
        provider=CallProvider.custom,
        provider_name="mock",
        status=CallStatus.completed,
    )
    normalized = call_transcript_to_normalized_conversation(
        _transcript(_agent_turn(metadata={"retrieved_chunks": [{"content": "Runtime context"}]})),
        rag_config=_rag_config(),
    )
    calling_result = CallingExecutionResult(
        status=CallingExecutionStatus.completed,
        call_session=session,
        normalized_conversation=normalized,
    )

    execution_result = CallingResultConverter().to_execution_result(calling_result)

    assert execution_result.transcript[0].rag_evidence.contexts == ["Runtime context"]


def test_calling_rag_reaches_existing_evaluation_service():
    normalized = call_transcript_to_normalized_conversation(
        _transcript(_agent_turn(metadata={"retrieved_chunks": [{"content": "Runtime context"}]})),
        rag_config=_rag_config(),
    )
    session = CallSession(direction=CallDirection.outbound, provider_name="mock", status=CallStatus.completed)
    calling_result = CallingExecutionResult(
        status=CallingExecutionStatus.completed,
        call_session=session,
        normalized_conversation=normalized,
    )
    execution_result = CallingResultConverter().to_execution_result(calling_result)
    captured = {}

    def fake_evaluate(**kwargs):
        captured.update(kwargs)
        return []

    with patch("app.evaluation_service.evaluate_transcript", side_effect=fake_evaluate):
        EvaluationService().evaluate(execution_result, _scenario())

    assert captured["rag_context"] is None
    assert captured["rag_evidence_by_turn"][0]["contexts"] == ["Runtime context"]


def test_calling_runtime_evidence_has_priority_over_scenario_rag_context():
    normalized = call_transcript_to_normalized_conversation(
        _transcript(_agent_turn(metadata={"retrieved_chunks": [{"content": "Runtime context"}]})),
        rag_config=_rag_config(),
        retrieval_context=["Scenario fallback"],
    )

    assert normalized.retrieval_context == ["Scenario fallback"]
    assert normalized.messages[0].rag_evidence.contexts == ["Runtime context"]


def test_plain_calling_transcript_without_evidence_remains_normal():
    transcript = _transcript(
        CallTranscriptTurn(speaker=TranscriptSpeaker.customer, text="Hello", turn_index=0),
        _agent_turn("Hi there", turn_index=1),
    )

    normalized = call_transcript_to_normalized_conversation(transcript, rag_config=_rag_config())

    assert [message.content for message in normalized.messages] == ["Hello", "Hi there"]
    assert all(message.rag_evidence is None for message in normalized.messages)


def test_mock_calling_behavior_remains_unchanged_without_rag_config():
    result = CallingEvaluationRuntimeRunner().run(
        _scenario(),
        provider_config=CallingProviderConfig(provider_name="mock"),
    )

    assert result.normalized_conversation.channel == "calling"
    assert all(message.rag_evidence is None for message in result.normalized_conversation.messages)


def test_provider_webhook_metadata_is_not_automatically_rag_evidence():
    transcript = _transcript(
        _agent_turn(
            metadata={
                "webhook_payload": {"retrieved_chunks": [{"content": "Do not extract from full payload"}]},
                "provider_json": {"sources": [{"title": "Do not extract"}]},
            }
        )
    )

    normalized = call_transcript_to_normalized_conversation(transcript, rag_config=_rag_config())

    assert normalized.messages[0].rag_evidence is None


def test_manual_calling_transcript_metadata_can_map_configured_rag_evidence():
    manual_transcript = NormalizedCallTranscript(
        session_id="manual-session",
        run_id="manual-run",
        source="manual_config",
        turns=[
            _agent_turn(
                metadata={"retrieved_chunks": [{"content": "Manual transcript context"}]},
            )
        ],
    )

    normalized = call_transcript_to_normalized_conversation(manual_transcript, rag_config=_rag_config())

    assert normalized.messages[0].rag_evidence.contexts == ["Manual transcript context"]
