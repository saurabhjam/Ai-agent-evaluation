from unittest.mock import patch

from app.evaluation_service import EvaluationService
from app.executor import ExecutionResult
from app.models.conversation import RAGEvidence
from app.models.voice import SessionStatus, Speaker, VoiceConversation, VoiceSession, VoiceTurn
from app.schemas import Persona, TestScenario
from app.voice.converter import voice_to_normalized_conversation
from app.voice.runner import _rag_evidence_by_turn


def _session() -> VoiceSession:
    return VoiceSession(session_id="voice-session-1", status=SessionStatus.completed)


def _conversation(*turns: VoiceTurn) -> VoiceConversation:
    return VoiceConversation(session=_session(), turns=list(turns))


def _rag_config(**overrides):
    config = {
        "enabled": True,
        "context_path": "metadata.retrieved_chunks[*].content",
        "citation_path": "metadata.sources[*]",
        "source_type": "agent_retrieval",
    }
    config.update(overrides)
    return config


def test_voice_agent_turn_with_inline_retrieval_context():
    vc = _conversation(
        VoiceTurn(speaker=Speaker.user, text="Can I get a refund?"),
        VoiceTurn(
            speaker=Speaker.agent,
            text="Refunds are available within 30 days.",
            metadata={"retrieved_chunks": [{"content": "Customers may request a refund within 30 days."}]},
        ),
    )

    normalized = voice_to_normalized_conversation(vc, rag_config=_rag_config())

    assert normalized.messages[1].rag_evidence.contexts == [
        "Customers may request a refund within 30 days."
    ]


def test_voice_rag_multiple_context_snippets():
    vc = _conversation(
        VoiceTurn(
            speaker=Speaker.agent,
            text="Here are the policy details.",
            metadata={"retrieved_chunks": [{"content": "Chunk A"}, {"content": "Chunk B"}]},
        )
    )

    normalized = voice_to_normalized_conversation(vc, rag_config=_rag_config())

    assert normalized.messages[0].rag_evidence.contexts == ["Chunk A", "Chunk B"]


def test_voice_rag_nested_metadata_mapping():
    vc = _conversation(
        VoiceTurn(
            speaker=Speaker.agent,
            text="Nested metadata answer.",
            metadata={"trace": {"retrieval": {"chunks": [{"text": "Nested chunk"}]}}},
        )
    )

    normalized = voice_to_normalized_conversation(
        vc,
        rag_config=_rag_config(context_path="metadata.trace.retrieval.chunks[*].text"),
    )

    assert normalized.messages[0].rag_evidence.contexts == ["Nested chunk"]


def test_voice_rag_citation_and_textual_context():
    vc = _conversation(
        VoiceTurn(
            speaker=Speaker.agent,
            text="The warranty is one year.",
            metadata={
                "retrieved_chunks": [{"content": "Warranty coverage lasts one year."}],
                "sources": [{"title": "Warranty Policy", "url": "https://example.test/warranty"}],
            },
        )
    )

    normalized = voice_to_normalized_conversation(vc, rag_config=_rag_config())

    evidence = normalized.messages[0].rag_evidence
    assert evidence.contexts == ["Warranty coverage lasts one year."]
    assert evidence.citations == [{"title": "Warranty Policy", "url": "https://example.test/warranty"}]


def test_voice_rag_citation_only_does_not_fabricate_context():
    vc = _conversation(
        VoiceTurn(
            speaker=Speaker.agent,
            text="The policy is in the help center.",
            metadata={"sources": [{"title": "Help Center", "url": "https://example.test/help"}]},
        )
    )

    normalized = voice_to_normalized_conversation(vc, rag_config=_rag_config())

    evidence = normalized.messages[0].rag_evidence
    assert evidence.contexts == []
    assert evidence.citations == [{"title": "Help Center", "url": "https://example.test/help"}]


def test_voice_rag_no_config_keeps_existing_behavior():
    vc = _conversation(
        VoiceTurn(
            speaker=Speaker.agent,
            text="Plain answer.",
            metadata={"retrieved_chunks": [{"content": "Should not be extracted"}]},
        )
    )

    normalized = voice_to_normalized_conversation(vc)

    assert normalized.messages[0].rag_evidence is None
    assert normalized.messages[0].metadata["retrieved_chunks"] == [{"content": "Should not be extracted"}]


def test_voice_rag_missing_context_path_has_no_evidence():
    vc = _conversation(VoiceTurn(speaker=Speaker.agent, text="Answer.", metadata={"other": []}))

    normalized = voice_to_normalized_conversation(vc, rag_config=_rag_config())

    assert normalized.messages[0].rag_evidence is None


def test_voice_rag_empty_context_has_no_evidence():
    vc = _conversation(
        VoiceTurn(speaker=Speaker.agent, text="Answer.", metadata={"retrieved_chunks": [{"content": "  "}]})
    )

    normalized = voice_to_normalized_conversation(vc, rag_config=_rag_config())

    assert normalized.messages[0].rag_evidence is None


def test_voice_rag_malformed_context_has_no_evidence():
    vc = _conversation(
        VoiceTurn(speaker=Speaker.agent, text="Answer.", metadata={"retrieved_chunks": [{"value": {"nested": True}}]})
    )

    normalized = voice_to_normalized_conversation(vc, rag_config=_rag_config())

    assert normalized.messages[0].rag_evidence is None


def test_voice_rag_extraction_exception_does_not_break_conversion():
    vc = _conversation(VoiceTurn(speaker=Speaker.agent, text="Answer.", metadata={"retrieved_chunks": []}))

    with patch("app.voice.converter.extract_rag_evidence", side_effect=RuntimeError("boom")):
        normalized = voice_to_normalized_conversation(vc, rag_config=_rag_config())

    assert normalized.messages[0].content == "Answer."
    assert normalized.messages[0].rag_evidence is None


def test_voice_rag_two_turns_retain_independent_evidence():
    vc = _conversation(
        VoiceTurn(speaker=Speaker.agent, text="Answer 1", metadata={"retrieved_chunks": [{"content": "C1"}]}),
        VoiceTurn(speaker=Speaker.agent, text="Answer 2", metadata={"retrieved_chunks": [{"content": "C2"}]}),
    )

    normalized = voice_to_normalized_conversation(vc, rag_config=_rag_config())

    assert normalized.messages[0].rag_evidence.contexts == ["C1"]
    assert normalized.messages[1].rag_evidence.contexts == ["C2"]


def test_voice_rag_evidence_from_turn_one_does_not_leak_into_turn_two():
    vc = _conversation(
        VoiceTurn(speaker=Speaker.agent, text="Answer 1", metadata={"retrieved_chunks": [{"content": "C1"}]}),
        VoiceTurn(speaker=Speaker.agent, text="Answer 2", metadata={"unrelated": "metadata"}),
    )

    normalized = voice_to_normalized_conversation(vc, rag_config=_rag_config())

    assert normalized.messages[0].rag_evidence.contexts == ["C1"]
    assert normalized.messages[1].rag_evidence is None


def test_voice_rag_explicit_turn_evidence_survives_normalization():
    vc = _conversation(
        VoiceTurn(
            speaker=Speaker.agent,
            text="Answer.",
            rag_evidence=RAGEvidence(available=True, source="agent_retrieval", contexts=["Explicit context"]),
        )
    )

    normalized = voice_to_normalized_conversation(vc)

    assert normalized.messages[0].rag_evidence.contexts == ["Explicit context"]


def test_voice_rag_reaches_existing_evaluation_service():
    vc = _conversation(
        VoiceTurn(speaker=Speaker.user, text="Question"),
        VoiceTurn(speaker=Speaker.agent, text="Answer", metadata={"retrieved_chunks": [{"content": "Runtime context"}]}),
    )
    normalized = voice_to_normalized_conversation(vc, rag_config=_rag_config())
    execution = ExecutionResult(
        success=True,
        connection_id="voice-1",
        agent_type="voice",
        adapter="voice",
        transcript=normalized.messages,
        started_at="2024-01-01T00:00:00Z",
        completed_at="2024-01-01T00:01:00Z",
    )
    scenario = TestScenario(
        scenario_id="voice-rag",
        description="Voice RAG test",
        persona=Persona(name="Ava", goal="Ask a policy question", tone="neutral", edge_case=""),
        agent={"channel": "voice"},
        rag_context=["Scenario fallback"],
        pass_threshold=0.5,
    )
    captured = {}

    def fake_evaluate(**kwargs):
        captured.update(kwargs)
        return []

    with patch("app.evaluation_service.evaluate_transcript", side_effect=fake_evaluate):
        EvaluationService().evaluate(execution, scenario)

    assert captured["rag_context"] is None
    assert captured["rag_evidence_by_turn"][0]["contexts"] == ["Runtime context"]


def test_voice_runtime_evidence_has_priority_over_scenario_rag_context():
    vc = _conversation(
        VoiceTurn(speaker=Speaker.agent, text="Answer", metadata={"retrieved_chunks": [{"content": "Runtime context"}]})
    )
    normalized = voice_to_normalized_conversation(vc, rag_config=_rag_config())

    assert normalized.messages[0].rag_evidence.contexts == ["Runtime context"]


def test_voice_runner_rag_evidence_helper_uses_runtime_context_only():
    vc = _conversation(
        VoiceTurn(speaker=Speaker.agent, text="Answer", metadata={"retrieved_chunks": [{"content": "Runtime context"}]})
    )
    normalized = voice_to_normalized_conversation(vc, rag_config=_rag_config())

    evidence = _rag_evidence_by_turn(normalized.messages)

    assert evidence == [
        {
            "actual_output": "Answer",
            "contexts": ["Runtime context"],
            "citations": None,
            "metadata": {"source_type": "agent_retrieval"},
            "source": "agent_retrieval",
        }
    ]


def test_plain_voice_transcript_without_evidence_remains_normal():
    vc = _conversation(
        VoiceTurn(speaker=Speaker.user, text="Hello"),
        VoiceTurn(speaker=Speaker.agent, text="Hi there"),
    )

    normalized = voice_to_normalized_conversation(vc, rag_config=_rag_config())

    assert [message.content for message in normalized.messages] == ["Hello", "Hi there"]
    assert all(message.rag_evidence is None for message in normalized.messages)
