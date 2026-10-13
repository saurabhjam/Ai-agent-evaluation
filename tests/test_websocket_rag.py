from __future__ import annotations

from app.adapters.chat.websocket import WebSocketChatAdapter


def _adapter(**config):
    base = {
        "endpoint": "wss://example.test/ws",
        "response_mapping": {"reply_field": "message"},
    }
    base.update(config)
    return WebSocketChatAdapter(base)


def test_websocket_json_answer_with_contexts():
    adapter = _adapter(
        rag_config={
            "enabled": True,
            "context_path": "sources[*].content",
            "citation_path": "sources[*]",
        }
    )

    answer = adapter.record_agent_response({
        "type": "answer",
        "message": "Refunds are available within 30 days.",
        "sources": [{"content": "Refund requests are accepted within 30 days."}],
    })

    turn = adapter.get_transcript()[-1]
    assert answer == "Refunds are available within 30 days."
    assert turn.rag_evidence.contexts == ["Refund requests are accepted within 30 days."]
    assert turn.rag_evidence.citations[0]["content"] == "Refund requests are accepted within 30 days."


def test_websocket_nested_contexts():
    adapter = _adapter(
        response_mapping={"reply_field": "data.answer"},
        rag_config={"enabled": True, "context_path": "data.references[*].text"},
    )

    adapter.record_agent_response({
        "event": "final_response",
        "data": {
            "answer": "Refunds are available.",
            "references": [{"text": "Refund policy text."}],
        },
    })

    assert adapter.get_transcript()[-1].content == "Refunds are available."
    assert adapter.get_transcript()[-1].rag_evidence.contexts == ["Refund policy text."]


def test_websocket_direct_list_contexts():
    adapter = _adapter(
        response_mapping={"reply_field": "answer"},
        rag_config={"enabled": True, "context_path": "retrieved_chunks"},
    )

    adapter.record_agent_response({
        "answer": "Refunds are available.",
        "retrieved_chunks": ["chunk one", "chunk two"],
    })

    assert adapter.get_transcript()[-1].rag_evidence.contexts == ["chunk one", "chunk two"]


def test_websocket_plain_text_answer_has_no_rag_evidence():
    adapter = _adapter()

    answer = adapter.record_agent_response("Your refund period is 30 days.")

    assert answer == "Your refund period is 30 days."
    assert adapter.get_transcript()[-1].rag_evidence is None


def test_websocket_missing_configured_context_path_has_no_rag_evidence():
    adapter = _adapter(
        response_mapping={"reply_field": "answer"},
        rag_config={"enabled": True, "context_path": "missing[*].content"},
    )

    adapter.record_agent_response({"answer": "Refunds are available."})

    assert adapter.get_transcript()[-1].rag_evidence is None


def test_websocket_empty_context_has_no_rag_evidence():
    adapter = _adapter(
        response_mapping={"reply_field": "answer"},
        rag_config={"enabled": True, "context_path": "chunks"},
    )

    adapter.record_agent_response({"answer": "Refunds are available.", "chunks": []})

    assert adapter.get_transcript()[-1].rag_evidence is None


def test_websocket_malformed_context_has_no_rag_evidence():
    adapter = _adapter(
        response_mapping={"reply_field": "answer"},
        rag_config={"enabled": True, "context_path": "chunks"},
    )

    adapter.record_agent_response({
        "answer": "Refunds are available.",
        "chunks": [{"document": "refunds.pdf"}],
    })

    assert adapter.get_transcript()[-1].rag_evidence is None


def test_websocket_two_turns_keep_evidence_turn_scoped():
    adapter = _adapter(
        response_mapping={"reply_field": "answer"},
        rag_config={"enabled": True, "context_path": "contexts"},
        responses=[
            {"answer": "Answer 1", "contexts": ["Context 1"]},
            {"answer": "Answer 2", "contexts": ["Context 2"]},
        ],
    )

    adapter.send_message("Question 1")
    adapter.send_message("Question 2")

    transcript = adapter.get_transcript()
    assert transcript[1].content == "Answer 1"
    assert transcript[1].rag_evidence.contexts == ["Context 1"]
    assert transcript[3].content == "Answer 2"
    assert transcript[3].rag_evidence.contexts == ["Context 2"]


def test_websocket_without_rag_config_remains_plain_response_stub():
    adapter = _adapter()

    response = adapter.send_message("Hello")

    assert response == "WebSocket response"
    assert adapter.get_transcript() == []


def test_websocket_partial_event_not_recorded_unless_processed_as_final():
    adapter = _adapter(
        response_mapping={"reply_field": "answer"},
        rag_config={"enabled": True, "context_path": "contexts"},
    )

    assert adapter.get_transcript() == []
    adapter.record_agent_response({"event": "final", "answer": "Done", "contexts": ["Final context"]})

    assert len(adapter.get_transcript()) == 1
    assert adapter.get_transcript()[0].content == "Done"
    assert adapter.get_transcript()[0].rag_evidence.contexts == ["Final context"]


def test_websocket_evidence_extraction_failure_does_not_fail_conversation(monkeypatch):
    import app.adapters.chat.websocket as websocket_module

    def fail_extract(*args, **kwargs):
        raise RuntimeError("bad mapping")

    monkeypatch.setattr(websocket_module, "extract_rag_evidence", fail_extract)
    adapter = _adapter(response_mapping={"reply_field": "answer"})

    answer = adapter.record_agent_response({"answer": "Still works."})

    assert answer == "Still works."
    assert adapter.get_transcript()[-1].rag_evidence is None
