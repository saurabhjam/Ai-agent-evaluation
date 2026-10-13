import requests
from unittest.mock import MagicMock, patch

from app.adapters.chat.rest import RestChatAdapter


def _response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.content = b"{}"
    response.headers = {"content-type": "application/json"}
    response.json.return_value = payload
    return response


def _adapter(**rag_overrides):
    rag_config = {
        "enabled": True,
        "mode": "separate_api",
        "correlation_path": "request_id",
        "evidence_request": {
            "method": "GET",
            "url": "https://client.example/evidence/{correlation_id}",
        },
        "context_path": "retrieved_chunks[*].content",
        "citation_path": "retrieved_chunks[*]",
        "source_type": "agent_retrieval",
    }
    rag_config.update(rag_overrides)
    return RestChatAdapter(
        config={
            "endpoint": "https://client.example/chat",
            "response_mapping": {"reply_field": "answer"},
            "rag_config": rag_config,
        }
    )


def test_same_response_rag_behavior_still_works_without_mode():
    adapter = RestChatAdapter(
        config={
            "endpoint": "https://client.example/chat",
            "response_mapping": {"reply_field": "answer"},
            "rag_config": {
                "enabled": True,
                "context_path": "sources[*].content",
                "citation_path": "sources[*]",
            },
        }
    )

    with patch("requests.request") as mock_request:
        mock_request.return_value = _response(
            {
                "answer": "Inline answer",
                "sources": [{"content": "Inline retrieval context", "url": "https://source.test"}],
            }
        )

        adapter.send_message("Question")

    assert mock_request.call_count == 1
    evidence = adapter.transcript[-1].rag_evidence
    assert evidence is not None
    assert evidence.contexts == ["Inline retrieval context"]
    assert evidence.citations == [{"content": "Inline retrieval context", "url": "https://source.test"}]


def test_separate_evidence_api_get_attaches_same_turn_evidence():
    adapter = _adapter()

    with patch("requests.request") as mock_request:
        mock_request.side_effect = [
            _response({"answer": "Answer", "request_id": "trace-123"}),
            _response({"retrieved_chunks": [{"content": "Runtime context", "document": "kb.md"}]}),
        ]

        adapter.send_message("Question")

    evidence_call = mock_request.call_args_list[1].kwargs
    assert evidence_call["method"] == "GET"
    assert evidence_call["url"] == "https://client.example/evidence/trace-123"
    evidence = adapter.transcript[-1].rag_evidence
    assert evidence is not None
    assert evidence.contexts == ["Runtime context"]
    assert evidence.citations == [{"content": "Runtime context", "document": "kb.md"}]


def test_separate_evidence_api_supports_post_body_and_nested_correlation():
    adapter = _adapter(
        correlation_path="meta.trace.id",
        evidence_request={
            "method": "POST",
            "url": "https://client.example/evidence",
            "json": {"trace_id": "{correlation_id}", "include": ["chunks"]},
        },
    )

    with patch("requests.request") as mock_request:
        mock_request.side_effect = [
            _response({"answer": "Answer", "meta": {"trace": {"id": "nested-1"}}}),
            _response({"retrieved_chunks": [{"content": "Nested context"}]}),
        ]

        adapter.send_message("Question")

    evidence_call = mock_request.call_args_list[1].kwargs
    assert evidence_call["method"] == "POST"
    assert evidence_call["json"] == {"trace_id": "nested-1", "include": ["chunks"]}
    assert adapter.transcript[-1].rag_evidence.contexts == ["Nested context"]


def test_separate_evidence_api_uses_same_headers_by_default():
    adapter = RestChatAdapter(
        config={
            "endpoint": "https://client.example/chat",
            "headers": {"X-Tenant": "acme"},
            "auth": {"type": "bearer", "value": "token"},
            "response_mapping": {"reply_field": "answer"},
            "rag_config": {
                "enabled": True,
                "mode": "separate_api",
                "correlation_path": "request_id",
                "evidence_request": {"url": "https://client.example/evidence/{correlation_id}"},
                "context_path": "chunks[*].text",
            },
        }
    )

    with patch("requests.request") as mock_request:
        mock_request.side_effect = [
            _response({"answer": "Answer", "request_id": "trace-1"}),
            _response({"chunks": [{"text": "Shared auth context"}]}),
        ]

        adapter.send_message("Question")

    headers = mock_request.call_args_list[1].kwargs["headers"]
    assert headers["Authorization"] == "Bearer token"
    assert headers["X-Tenant"] == "acme"


def test_separate_evidence_api_supports_custom_headers_without_same_auth(monkeypatch):
    monkeypatch.setenv("EVIDENCE_TOKEN", "evidence-secret")
    adapter = _adapter(
        evidence_request={
            "method": "GET",
            "url": "https://evidence.example/{correlation_id}",
            "use_same_auth": False,
            "headers": {"X-Evidence": "env:EVIDENCE_TOKEN"},
        }
    )

    with patch("requests.request") as mock_request:
        mock_request.side_effect = [
            _response({"answer": "Answer", "request_id": "trace-1"}),
            _response({"retrieved_chunks": [{"content": "Custom auth context"}]}),
        ]

        adapter.send_message("Question")

    assert mock_request.call_args_list[1].kwargs["headers"] == {"X-Evidence": "evidence-secret"}


def test_separate_evidence_api_supports_separate_bearer_auth(monkeypatch):
    monkeypatch.setenv("EVIDENCE_BEARER", "evidence-token")
    adapter = _adapter(
        evidence_request={
            "url": "https://evidence.example/{correlation_id}",
            "use_same_auth": False,
            "auth": {"type": "bearer", "value": "env:EVIDENCE_BEARER"},
        }
    )

    with patch("requests.request") as mock_request:
        mock_request.side_effect = [
            _response({"answer": "Answer", "request_id": "trace-1"}),
            _response({"retrieved_chunks": [{"content": "Separate auth context"}]}),
        ]

        adapter.send_message("Question")

    assert mock_request.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer evidence-token"


def test_no_correlation_means_no_evidence_request():
    adapter = _adapter()

    with patch("requests.request") as mock_request:
        mock_request.return_value = _response({"answer": "Answer"})

        adapter.send_message("Question")

    assert mock_request.call_count == 1
    assert adapter.transcript[-1].rag_evidence is None


def test_evidence_api_timeout_does_not_fail_conversation():
    adapter = _adapter()

    with patch("requests.request") as mock_request:
        mock_request.side_effect = [
            _response({"answer": "Answer", "request_id": "trace-1"}),
            requests.exceptions.Timeout(),
        ]

        reply = adapter.send_message("Question")

    assert reply == "Answer"
    assert adapter.transcript[-1].rag_evidence is None


def test_evidence_api_http_failure_does_not_fail_conversation():
    adapter = _adapter()
    failing_response = _response({"error": "nope"}, status_code=500)
    failing_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=failing_response)

    with patch("requests.request") as mock_request:
        mock_request.side_effect = [
            _response({"answer": "Answer", "request_id": "trace-1"}),
            failing_response,
        ]

        reply = adapter.send_message("Question")

    assert reply == "Answer"
    assert adapter.transcript[-1].rag_evidence is None


def test_malformed_evidence_api_response_does_not_fail_conversation():
    adapter = _adapter()
    malformed_response = _response({})
    malformed_response.json.side_effect = ValueError("bad json")

    with patch("requests.request") as mock_request:
        mock_request.side_effect = [
            _response({"answer": "Answer", "request_id": "trace-1"}),
            malformed_response,
        ]

        adapter.send_message("Question")

    assert adapter.transcript[-1].rag_evidence is None


def test_missing_evidence_paths_leave_rag_empty():
    adapter = _adapter()

    with patch("requests.request") as mock_request:
        mock_request.side_effect = [
            _response({"answer": "Answer", "request_id": "trace-1"}),
            _response({"other": [{"content": "not configured"}]}),
        ]

        adapter.send_message("Question")

    assert adapter.transcript[-1].rag_evidence is None


def test_database_rows_are_not_treated_as_rag_without_explicit_path():
    adapter = _adapter(context_path="retrieved_chunks[*].content")

    with patch("requests.request") as mock_request:
        mock_request.side_effect = [
            _response({"answer": "Answer", "request_id": "trace-1"}),
            _response({"rows": [{"answer": "database row"}], "answer": "plain answer"}),
        ]

        adapter.send_message("Question")

    assert adapter.transcript[-1].rag_evidence is None


def test_rag_evidence_is_isolated_to_each_turn():
    adapter = _adapter()

    with patch("requests.request") as mock_request:
        mock_request.side_effect = [
            _response({"answer": "First", "request_id": "trace-1"}),
            _response({"retrieved_chunks": [{"content": "First context"}]}),
            _response({"answer": "Second"}),
        ]

        adapter.send_message("First question")
        adapter.send_message("Second question")

    assert adapter.transcript[1].rag_evidence.contexts == ["First context"]
    assert adapter.transcript[3].rag_evidence is None


def test_rag_config_serializes_inside_connection_model():
    from app.models.connection import AgentConnection, AgentType

    connection = AgentConnection(
        id="rag-rest",
        name="RAG REST",
        type=AgentType.chatbot,
        adapter="rest",
        config={
            "endpoint": "https://client.example/chat",
            "rag_config": {
                "enabled": True,
                "mode": "separate_api",
                "correlation_path": "request_id",
                "evidence_request": {"url": "https://client.example/evidence/{correlation_id}"},
                "context_path": "chunks[*].content",
            },
        },
    )

    reloaded = AgentConnection(**connection.model_dump())
    assert reloaded.config["rag_config"]["mode"] == "separate_api"
    assert reloaded.config["rag_config"]["evidence_request"]["url"].endswith("{correlation_id}")
