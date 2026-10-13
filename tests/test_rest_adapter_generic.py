import pytest
from unittest.mock import patch
from app.adapters.chat.rest import RestChatAdapter
class MockMessage:
    def __init__(self, role, content):
        self.role = role
        self.content = content

def test_a_no_request_mapping_legacy_behavior():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
    })
    adapter.session_id = "test-sess"
    
    # Send mock request
    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {"reply": "Hi"}
        
        adapter.send_message("Hello")
        
        called_kwargs = mock_req.call_args.kwargs
        payload = called_kwargs["json"]
        
        assert "message" in payload
        assert payload["message"] == "Hello"
        # Since session_id_field wasn't configured, session_id is not injected
        assert "session_id" not in payload


def test_rest_adapter_captures_configured_rag_evidence_from_sources():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "response_mapping": {"reply_field": "answer"},
        "rag_config": {
            "enabled": True,
            "context_path": "sources[*].content",
            "citation_path": "sources[*]",
            "source_type": "agent_retrieval",
        },
    })

    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {
            "answer": "Returns are allowed within 30 days.",
            "sources": [
                {
                    "content": "Customers can return products within 30 days.",
                    "document": "refund_policy.pdf",
                }
            ],
        }

        reply = adapter.send_message("What is the return policy?")

    assert reply == "Returns are allowed within 30 days."
    agent_turn = adapter.get_transcript()[-1]
    assert agent_turn.content == "Returns are allowed within 30 days."
    assert agent_turn.rag_evidence is not None
    assert agent_turn.rag_evidence.available is True
    assert agent_turn.rag_evidence.source == "agent_retrieval"
    assert agent_turn.rag_evidence.contexts == ["Customers can return products within 30 days."]
    assert agent_turn.rag_evidence.citations[0]["document"] == "refund_policy.pdf"


def test_rest_adapter_captures_direct_list_rag_context_path():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "response_mapping": {"reply_field": "answer"},
        "rag_config": {
            "enabled": True,
            "context_path": "retrieved_chunks",
        },
    })

    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {
            "answer": "Refunds are allowed.",
            "retrieved_chunks": [
                "Refunds are allowed within 30 days.",
                "",
                None,
            ],
        }

        adapter.send_message("What is the refund policy?")

    assert adapter.get_transcript()[-1].rag_evidence.contexts == ["Refunds are allowed within 30 days."]


def test_rest_adapter_answer_only_has_no_rag_evidence():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "response_mapping": {"reply_field": "answer"},
    })

    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {"answer": "Hello"}

        adapter.send_message("Hi")

    assert adapter.get_transcript()[-1].content == "Hello"
    assert adapter.get_transcript()[-1].rag_evidence is None


def test_rest_adapter_missing_rag_path_continues_without_evidence():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "response_mapping": {"reply_field": "answer"},
        "rag_config": {
            "enabled": True,
            "context_path": "missing[*].content",
        },
    })

    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {"answer": "Hello"}

        adapter.send_message("Hi")

    assert adapter.get_transcript()[-1].content == "Hello"
    assert adapter.get_transcript()[-1].rag_evidence is None


def test_rest_adapter_ignores_malformed_empty_rag_context():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "response_mapping": {"reply_field": "answer"},
        "rag_config": {
            "enabled": True,
            "context_path": "sources[*]",
        },
    })

    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {
            "answer": "Hello",
            "sources": [{"document": "missing-content.pdf"}, "", None],
        }

        adapter.send_message("Hi")

    assert adapter.get_transcript()[-1].rag_evidence is None

def test_b_explicit_mapping_no_automatic_message():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "request_mapping": {
            "static_fields": {"model": "gemini"}
            # message_field intentionally missing
        }
    })
    
    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {"reply": "Hi"}
        
        adapter.send_message("Hello")
        
        payload = mock_req.call_args.kwargs["json"]
        
        assert payload == {"model": "gemini"}
        assert "message" not in payload

def test_c_explicit_mapping_no_automatic_session_id():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "request_mapping": {
            "message_field": "prompt"
            # session_id_field intentionally missing
        }
    })
    adapter.session_id = "sess-123"
    
    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {"reply": "Hi"}
        
        adapter.send_message("Hello")
        
        payload = mock_req.call_args.kwargs["json"]
        
        assert payload == {"prompt": "Hello"}
        assert "session_id" not in payload
        assert "sess-123" not in str(payload)

def test_d_nested_array_mapping():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "request_mapping": {
            "static_fields": {
                "contents[0].role": "user"
            },
            "message_field": "contents[0].parts[0].text"
        }
    })
    
    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {"reply": "Hi"}
        
        adapter.send_message("Hello")
        
        payload = mock_req.call_args.kwargs["json"]
        
        expected = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": "Hello"}
                    ]
                }
            ]
        }
        assert payload == expected

def test_e_conversation_history_mapping():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "request_mapping": {
            "history_field": "contents",
            "history_item_template": {
                "role": "{{role}}",
                "parts": [{"text": "{{message}}"}]
            },
            "history_role_map": {
                "user": "user",
                "agent": "model"
            }
        }
    })
    
    # inject fake transcript
    adapter.transcript = [
        MockMessage(role="user", content="Hello"),
        MockMessage(role="agent", content="Hi"),
        MockMessage(role="user", content="My product is damaged")
    ]
    
    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {"reply": "Ok"}
        
        adapter.send_message("...") # message value doesn't matter much when history is used
        
        payload = mock_req.call_args.kwargs["json"]
        
        expected = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "Hello"}]
                },
                {
                    "role": "model",
                    "parts": [{"text": "Hi"}]
                },
                {
                    "role": "user",
                    "parts": [{"text": "My product is damaged"}]
                },
                {
                    "role": "simulated_user",
                    "parts": [{"text": "..."}]
                }
            ]
        }
        
        assert payload == expected

def test_f_arbitrary_non_gemini_schema():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "request_mapping": {
            "static_fields": {
                "bot_id": "bot-xyz",
                "channel": "web"
            },
            "message_field": "input.message",
            "session_id_field": "input.conversation_id"
        }
    })
    adapter.session_id = "conv-999"
    
    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {"reply": "Hi"}
        
        adapter.send_message("Testing")
        
        payload = mock_req.call_args.kwargs["json"]
        
        expected = {
            "bot_id": "bot-xyz",
            "channel": "web",
            "input": {
                "message": "Testing",
                "conversation_id": "conv-999"
            }
        }
        
        assert payload == expected

def test_g_existing_laravel_adapter_tests():
    # Similar to test A, just proving backward compat explicitly
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
    })
    adapter.session_id = "sess-1"
    
    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {"reply": "Hi"}
        
        adapter.send_message("Legacy payload test")
        
        payload = mock_req.call_args.kwargs["json"]
        
        # When request_mapping is missing, defaults apply
        assert payload == {"message": "Legacy payload test"}

import os

def test_h_auth_api_key_custom_header(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "secret123")
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "auth": {
            "type": "api_key",
            "value": "env:TEST_API_KEY"
        },
        "api_key_header": "x-test-api-key"
    })
    assert adapter.headers.get("x-test-api-key") == "secret123"

def test_i_auth_bearer(monkeypatch):
    monkeypatch.setenv("TEST_TOKEN", "token456")
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "auth": {
            "type": "bearer",
            "value": "env:TEST_TOKEN"
        }
    })
    assert adapter.headers.get("Authorization") == "Bearer token456"

def test_j_auth_missing_env_var():
    with pytest.raises(ValueError, match="Environment variable 'MISSING_VAR' not found"):
        RestChatAdapter(config={
            "endpoint": "http://test",
            "auth": {
                "type": "bearer",
                "value": "env:MISSING_VAR"
            }
        })

def test_k_auth_existing_headers_preserved(monkeypatch):
    monkeypatch.setenv("TEST_TOKEN", "token456")
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "headers": {
            "Custom-Header": "StaticValue"
        },
        "auth": {
            "type": "bearer",
            "value": "env:TEST_TOKEN"
        }
    })
    assert adapter.headers.get("Authorization") == "Bearer token456"
    assert adapter.headers.get("Custom-Header") == "StaticValue"

def test_l_response_extraction_text_path():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "response_mapping": {
            "text_path": "candidates[0].content.parts[0].text"
        }
    })
    
    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Hello extracted text"}
                        ]
                    }
                }
            ]
        }
        
        adapter.send_message("Testing")
        assert len(adapter.transcript) == 2
        assert adapter.transcript[-1].content == "Hello extracted text"

def test_m_response_extraction_fallback():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        # no response_mapping
    })
    
    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {"reply": "Fallback works"}
        
        adapter.send_message("Testing")
        assert adapter.transcript[-1].content == "Fallback works"


def test_n_rest_response_preserves_conventional_ui_components_and_attachments():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "response_mapping": {"reply_field": "answer"},
    })

    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {
            "answer": "Choose one",
            "buttons": [{"label": "Book Appointment", "value": "book"}],
            "tables": [{"headers": ["Slot"], "rows": [["14:30"]]}],
            "forms": [{"title": "Contact", "fields": [{"label": "Email", "type": "email"}]}],
            "attachments": [{"url": "https://example.test/policy.pdf", "name": "policy.pdf"}],
            "images": [{"url": "https://example.test/damage.jpg", "name": "damage.jpg"}],
        }

        adapter.send_message("Testing")

    agent_msg = adapter.transcript[-1]
    assert agent_msg.content == "Choose one"
    assert agent_msg.attachments == ["https://example.test/policy.pdf", "https://example.test/damage.jpg"]
    assert agent_msg.metadata["components"] == [
        {"type": "button", "label": "Book Appointment", "value": "book"},
        {"type": "table", "headers": ["Slot"], "rows": [["14:30"]]},
        {"type": "form", "title": "Contact", "fields": [{"label": "Email", "type": "email"}]},
        {"type": "attachment", "url": "https://example.test/policy.pdf", "name": "policy.pdf"},
        {"type": "image", "url": "https://example.test/damage.jpg", "name": "damage.jpg"},
    ]


def test_o_rest_response_preserves_configured_nested_ui_component_fields():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "response_mapping": {
            "reply_field": "data.answer",
            "buttons_field": "data.ui.actions",
            "attachments_field": "data.ui.files",
        },
    })

    with patch("requests.request") as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {
            "data": {
                "answer": "Here are actions",
                "ui": {
                    "actions": ["Approve", "Reject"],
                    "files": [{"download_url": "https://example.test/report.csv", "filename": "report.csv"}],
                },
            }
        }

        adapter.send_message("Testing")

    agent_msg = adapter.transcript[-1]
    assert agent_msg.content == "Here are actions"
    assert agent_msg.attachments == ["https://example.test/report.csv"]
    assert agent_msg.metadata["components"] == [
        {"type": "button", "label": "Approve"},
        {"type": "button", "label": "Reject"},
        {"type": "attachment", "download_url": "https://example.test/report.csv", "filename": "report.csv"},
    ]

def test_p_conversation_state_propagation():
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "request_mapping": {
            "message_field": "question",
            "conversation_id_field": "meta.conversation_id"
        },
        "response_mapping": {
            "reply_field": "answer",
            "conversation_id_field": "conversation_id"
        }
    })
    
    with patch("requests.request") as mock_req:
        # Turn 1
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {
            "answer": "Hello",
            "conversation_id": "conv_abc123"
        }
        
        adapter.send_message("Hi")
        
        # Verify Turn 1 request did NOT include conversation_id
        payload = mock_req.call_args[1]["json"]
        assert payload["question"] == "Hi"
        assert "meta" not in payload or "conversation_id" not in payload.get("meta", {})
        
        # Turn 2
        mock_req.return_value.json.return_value = {
            "answer": "World",
            "conversation_id": "conv_abc123"
        }
        
        adapter.send_message("Next")
        
        # Verify Turn 2 request DID include conversation_id
        payload2 = mock_req.call_args[1]["json"]
        assert payload2["question"] == "Next"
        assert payload2["meta"]["conversation_id"] == "conv_abc123"
