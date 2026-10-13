import requests

from app.backend_validation import BackendValidationEngine
from app.models.conversation import ConversationMessage
from app.schemas import AgentConfig, Persona, TestScenario


def _scenario(config=None):
    return TestScenario(
        scenario_id="backend-validation",
        agent=AgentConfig(channel="chatbot", adapter="rest", config=config or {}),
        persona=Persona(name="Rahul", goal="Complete a support request", tone="polite"),
    )


def test_backend_validation_returns_not_configured_without_checks():
    result = BackendValidationEngine().validate([], _scenario())

    assert result.status == "not_configured"
    assert result.passed is None
    assert result.checks == []


def test_backend_validation_consumes_completed_transcript_only():
    transcript = [
        ConversationMessage(role="simulated_user", content="I need help.", turn_index=0),
        ConversationMessage(role="agent", content="Your ticket was created.", turn_index=1),
    ]
    scenario = _scenario(
        {
            "backend_validation": {
                "expected_phrases": ["ticket was created"],
                "forbidden_phrases": ["payment failed"],
                "min_agent_turns": 1,
                "min_user_turns": 1,
            }
        }
    )

    result = BackendValidationEngine().validate(transcript, scenario)

    assert result.status == "validated"
    assert result.passed is True
    assert len(result.checks) == 4


def test_backend_validation_reports_failed_checks():
    scenario = _scenario({"backend_validation": {"expected_phrases": ["appointment confirmed"]}})

    result = BackendValidationEngine().validate(
        [{"role": "agent", "content": "I cannot confirm this yet."}],
        scenario,
    )

    assert result.status == "validated"
    assert result.passed is False
    assert result.checks[0].name == "Expected phrase"


def test_rest_backend_validation_executes_configured_request(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = '{"status":"OPEN","priority":"HIGH","unit":"4B"}'
        headers = {"x-request-id": "req-123"}

        def json(self):
            return {"status": "OPEN", "priority": "HIGH", "unit": "4B"}

    def request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        return Response()

    monkeypatch.setattr("app.backend_validation.validators.rest.requests.request", request)
    scenario = _scenario(
        {
            "base_url": "https://example.test",
            "backend_validation": [
                {
                    "name": "Verify Maintenance Ticket",
                    "type": "rest",
                    "variables": {"ticket_id": "12345"},
                    "request": {
                        "method": "GET",
                        "url": "{{base_url}}/maintenance/{{ticket_id}}",
                        "headers": {"X-Test": "yes"},
                        "query": {"include": "details"},
                        "bearer_token": "token-1",
                        "timeout": 3,
                        "verify_ssl": False,
                    },
                    "expect": {"status": "OPEN", "priority": "HIGH", "unit": "4B"},
                }
            ],
        }
    )

    result = BackendValidationEngine().validate([], scenario)

    assert result.status == "PASS"
    assert result.passed is True
    assert captured["method"] == "GET"
    assert captured["url"] == "https://example.test/maintenance/12345"
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer token-1"
    assert captured["kwargs"]["params"] == {"include": "details"}
    assert captured["kwargs"]["timeout"] == 3
    assert captured["kwargs"]["verify"] is False
    assert result.checks[0].evidence["status_code"] == 200
    assert result.checks[0].evidence["request_id"] == "req-123"


def test_rest_backend_validation_reports_failed_expectation(monkeypatch):
    class Response:
        status_code = 200
        text = '{"status":"CLOSED"}'
        headers = {}

        def json(self):
            return {"status": "CLOSED"}

    monkeypatch.setattr(
        "app.backend_validation.validators.rest.requests.request",
        lambda *args, **kwargs: Response(),
    )
    scenario = _scenario(
        {
            "backend_validation": {
                "name": "Verify Ticket",
                "type": "rest",
                "request": {"method": "GET", "url": "https://example.test/ticket/1"},
                "expect": {"status": "OPEN"},
            }
        }
    )

    result = BackendValidationEngine().validate([], scenario)

    assert result.status == "FAIL"
    assert result.passed is False
    assert result.checks[-1].expected == "OPEN"
    assert result.checks[-1].actual == "CLOSED"


def test_rest_backend_validation_supports_write_methods_and_json_body(monkeypatch):
    calls = []

    class Response:
        status_code = 204
        text = ""
        headers = {}

        def json(self):
            raise ValueError("no json")

    def request(method, url, **kwargs):
        calls.append((method, kwargs.get("json")))
        return Response()

    monkeypatch.setattr("app.backend_validation.validators.rest.requests.request", request)
    for method in ["POST", "PUT", "PATCH", "DELETE"]:
        scenario = _scenario(
            {
                "backend_validation": {
                    "name": f"{method} validation",
                    "type": "rest",
                    "request": {
                        "method": method,
                        "url": "https://example.test/resource",
                        "json": {"status": "checked"},
                    },
                }
            }
        )

        result = BackendValidationEngine().validate([], scenario)

        assert result.status == "PASS"

    assert calls == [
        ("POST", {"status": "checked"}),
        ("PUT", {"status": "checked"}),
        ("PATCH", {"status": "checked"}),
        ("DELETE", {"status": "checked"}),
    ]


def test_rest_backend_validation_handles_request_error(monkeypatch):
    def request(*args, **kwargs):
        raise requests.Timeout("boom")

    monkeypatch.setattr("app.backend_validation.validators.rest.requests.request", request)
    scenario = _scenario(
        {
            "backend_validation": {
                "name": "Backend check",
                "type": "rest",
                "request": {"method": "GET", "url": "https://example.test/fail"},
            }
        }
    )

    result = BackendValidationEngine().validate([], scenario)

    assert result.status == "ERROR"
    assert result.passed is False


def test_backend_validation_extracts_regex_variable_for_template(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = '{"status":"OPEN"}'
        headers = {}

        def json(self):
            return {"status": "OPEN"}

    def request(method, url, **kwargs):
        captured["url"] = url
        return Response()

    monkeypatch.setattr("app.backend_validation.validators.rest.requests.request", request)
    transcript = [{"role": "agent", "content": "Ticket ID: MT-10234 was created."}]
    scenario = _scenario(
        {
            "base_url": "https://example.test",
            "backend_validation": {
                "name": "Verify ticket",
                "type": "rest",
                "variables": {"ticket_id": {"regex": r"Ticket ID:\s*(\w+-\d+)"}},
                "request": {"method": "GET", "url": "{{base_url}}/maintenance/{{ticket_id}}"},
                "expect": {"status": "OPEN"},
            },
        }
    )

    result = BackendValidationEngine().validate(transcript, scenario)

    assert result.status == "PASS"
    assert captured["url"] == "https://example.test/maintenance/MT-10234"
    assert result.checks[0].evidence["extracted_variables"] == {"ticket_id": "MT-10234"}


def test_backend_validation_extracts_transcript_variable_by_speaker(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = '{"status":"FOUND"}'
        headers = {}

        def json(self):
            return {"status": "FOUND"}

    def request(method, url, **kwargs):
        captured["url"] = url
        return Response()

    monkeypatch.setattr("app.backend_validation.validators.rest.requests.request", request)
    transcript = [
        {"role": "agent", "content": "Which order?"},
        {"role": "user", "content": "Order #10042"},
    ]
    scenario = _scenario(
        {
            "base_url": "https://example.test",
            "backend_validation": {
                "name": "Verify order",
                "type": "rest",
                "variables": {
                    "order_number": {
                        "speaker": "user",
                        "regex": r"Order #(\d+)",
                    }
                },
                "request": {"url": "{{base_url}}/orders/{{order_number}}"},
                "expect": {"status": "FOUND"},
            },
        }
    )

    result = BackendValidationEngine().validate(transcript, scenario)

    assert result.status == "PASS"
    assert captured["url"] == "https://example.test/orders/10042"


def test_backend_validation_extracts_metadata_json_path(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = '{"status":"REFUNDED"}'
        headers = {}

        def json(self):
            return {"status": "REFUNDED"}

    def request(method, url, **kwargs):
        captured["url"] = url
        return Response()

    monkeypatch.setattr("app.backend_validation.validators.rest.requests.request", request)
    transcript = [
        {
            "role": "agent",
            "content": "Refund created.",
            "metadata": {"refund": {"id": "RF-1002"}},
        }
    ]
    scenario = _scenario(
        {
            "base_url": "https://example.test",
            "backend_validation": {
                "name": "Verify refund",
                "type": "rest",
                "variables": {
                    "refund_id": {
                        "source": "metadata",
                        "path": "$.refund.id",
                    }
                },
                "request": {"url": "{{base_url}}/refunds/{{refund_id}}"},
                "expect": {"status": "REFUNDED"},
            },
        }
    )

    result = BackendValidationEngine().validate(transcript, scenario)

    assert result.status == "PASS"
    assert captured["url"] == "https://example.test/refunds/RF-1002"


def test_backend_validation_missing_variable_resolves_to_empty_string(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = "{}"
        headers = {}

        def json(self):
            return {}

    def request(method, url, **kwargs):
        captured["url"] = url
        return Response()

    monkeypatch.setattr("app.backend_validation.validators.rest.requests.request", request)
    scenario = _scenario(
        {
            "base_url": "https://example.test",
            "backend_validation": {
                "name": "Missing variable",
                "type": "rest",
                "variables": {"ticket_id": {"regex": r"Ticket ID:\s*(\w+-\d+)"}},
                "request": {"url": "{{base_url}}/maintenance/{{ticket_id}}"},
            },
        }
    )

    result = BackendValidationEngine().validate([], scenario)

    assert result.status == "PASS"
    assert captured["url"] == "https://example.test/maintenance/"
    assert result.checks[0].evidence["extracted_variables"] == {}


def test_backend_validation_extracts_multiple_variables(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = '{"status":"OPEN"}'
        headers = {}

        def json(self):
            return {"status": "OPEN"}

    def request(method, url, **kwargs):
        captured["url"] = url
        return Response()

    monkeypatch.setattr("app.backend_validation.validators.rest.requests.request", request)
    transcript = [{"role": "agent", "content": "Ticket ID: MT-10234 for Order #10042"}]
    scenario = _scenario(
        {
            "base_url": "https://example.test",
            "backend_validation": {
                "name": "Verify linked ticket",
                "type": "rest",
                "variables": {
                    "ticket_id": {"regex": r"Ticket ID:\s*(\w+-\d+)"},
                    "order_number": {"regex": r"Order #(\d+)"},
                },
                "request": {"url": "{{base_url}}/orders/{{order_number}}/tickets/{{ticket_id}}"},
                "expect": {"status": "OPEN"},
            },
        }
    )

    result = BackendValidationEngine().validate(transcript, scenario)

    assert result.status == "PASS"
    assert captured["url"] == "https://example.test/orders/10042/tickets/MT-10234"
    assert result.checks[0].evidence["extracted_variables"] == {
        "ticket_id": "MT-10234",
        "order_number": "10042",
    }


def test_backend_validation_static_variables_remain_backward_compatible(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = '{"status":"OPEN"}'
        headers = {}

        def json(self):
            return {"status": "OPEN"}

    def request(method, url, **kwargs):
        captured["url"] = url
        return Response()

    monkeypatch.setattr("app.backend_validation.validators.rest.requests.request", request)
    scenario = _scenario(
        {
            "base_url": "https://example.test",
            "backend_validation": {
                "name": "Verify static ticket",
                "type": "rest",
                "variables": {"ticket_id": "12345"},
                "request": {"url": "{{base_url}}/maintenance/{{ticket_id}}"},
                "expect": {"status": "OPEN"},
            },
        }
    )

    result = BackendValidationEngine().validate([], scenario)

    assert result.status == "PASS"
    assert captured["url"] == "https://example.test/maintenance/12345"
    assert result.checks[0].evidence["extracted_variables"] == {}


def test_backend_validation_uses_connection_level_rest_config(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = '{"status":"OPEN"}'
        headers = {}

        def json(self):
            return {"status": "OPEN"}

    def request(method, url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return Response()

    monkeypatch.setattr("app.backend_validation.validators.rest.requests.request", request)
    scenario = _scenario(
        {
            "backend_validation": [
                {
                    "name": "Verify Maintenance Ticket",
                    "backend": "primary-rest",
                    "type": "rest",
                    "request": {"method": "GET", "url": "/maintenance/MT-10234"},
                    "expect": {"$.status": {"equals": "OPEN"}},
                }
            ],
            "backend_validation_connections": {
                "enabled": True,
                "connections": [
                    {
                        "id": "primary-rest",
                        "name": "Production REST API",
                        "type": "rest",
                        "base_url": "https://api.example.test",
                        "authentication": {"type": "bearer", "token": "secret-token"},
                        "timeout": 30,
                        "verify_ssl": False,
                    }
                ],
            },
        }
    )

    result = BackendValidationEngine().validate([], scenario)

    assert result.status == "PASS"
    assert captured["url"] == "https://api.example.test/maintenance/MT-10234"
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["kwargs"]["timeout"] == 30
    assert captured["kwargs"]["verify"] is False
    assert result.checks[0].evidence["backend_connection"]["name"] == "Production REST API"


def test_backend_validation_connection_level_config_takes_precedence(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = '{"status":"OPEN"}'
        headers = {}

        def json(self):
            return {"status": "OPEN"}

    def request(method, url, **kwargs):
        captured["url"] = url
        return Response()

    monkeypatch.setattr("app.backend_validation.validators.rest.requests.request", request)
    scenario = _scenario(
        {
            "base_url": "https://scenario.example.test",
            "backend_validation": {
                "name": "Verify Ticket",
                "backend": "primary-rest",
                "type": "rest",
                "request": {"url": "/tickets/1"},
                "expect": {"status": "OPEN"},
            },
            "backend_validation_connections": {
                "enabled": True,
                "connections": [
                    {
                        "id": "primary-rest",
                        "name": "Connection REST API",
                        "type": "rest",
                        "base_url": "https://connection.example.test",
                    }
                ],
            },
        }
    )

    result = BackendValidationEngine().validate([], scenario)

    assert result.status == "PASS"
    assert captured["url"] == "https://connection.example.test/tickets/1"


def test_backend_validation_selects_named_connection_from_multiple(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = '{"status":"OPEN"}'
        headers = {}

        def json(self):
            return {"status": "OPEN"}

    def request(method, url, **kwargs):
        captured["url"] = url
        return Response()

    monkeypatch.setattr("app.backend_validation.validators.rest.requests.request", request)
    scenario = _scenario(
        {
            "backend_validation": [
                {
                    "name": "Verify Ticket",
                    "backend": "secondary-rest",
                    "type": "rest",
                    "request": {"url": "/tickets/1"},
                    "expect": {"status": "OPEN"},
                }
            ],
            "backend_validation_connections": {
                "enabled": True,
                "connections": [
                    {"id": "primary-rest", "name": "Primary", "type": "rest", "base_url": "https://primary.test"},
                    {"id": "secondary-rest", "name": "Secondary", "type": "rest", "base_url": "https://secondary.test"},
                ],
            },
        }
    )

    result = BackendValidationEngine().validate([], scenario)

    assert result.status == "PASS"
    assert captured["url"] == "https://secondary.test/tickets/1"
