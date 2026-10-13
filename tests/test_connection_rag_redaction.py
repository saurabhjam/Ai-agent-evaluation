from app.connections.api import _safe_connection_config


def test_connection_response_redacts_nested_rag_evidence_auth_value():
    safe = _safe_connection_config(
        {
            "endpoint": "https://client.example/chat",
            "auth": {"type": "bearer", "value": "chat-secret"},
            "rag_config": {
                "enabled": True,
                "mode": "separate_api",
                "correlation_path": "request_id",
                "context_path": "retrieved_chunks[*].content",
                "evidence_request": {
                    "url": "https://client.example/evidence/{correlation_id}",
                    "auth": {"type": "bearer", "value": "evidence-secret"},
                },
            },
        }
    )

    assert safe["auth"]["value"] == ""
    assert safe["rag_config"]["evidence_request"]["auth"]["value"] == ""
    assert safe["rag_config"]["mode"] == "separate_api"
    assert safe["rag_config"]["evidence_request"]["url"].endswith("{correlation_id}")
