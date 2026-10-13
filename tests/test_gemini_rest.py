import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import requests

from app.main import app
from app.adapters.chat.rest import RestChatAdapter
from app.schemas import TestScenario
from app.models.conversation import ConversationMessage

client = TestClient(app)

def test_rest_request_mapping():
    config = {
        "endpoint": "http://example.com/api",
        "request_mapping": {
            "message_template": "{\"text\": \"{{message}}\"}",
            "message_field": "query"
        },
        "response_mapping": {
            "reply_field": "answer"
        }
    }
    adapter = RestChatAdapter(config)
    with patch("requests.request") as mock_req:
        mock_response = MagicMock()
        mock_response.json.return_value = {"answer": "hello"}
        mock_req.return_value = mock_response
        
        reply = adapter.send_message("hi there")
        
        assert reply == "hello"
        mock_req.assert_called_once()
        kwargs = mock_req.call_args.kwargs
        assert kwargs["json"]["query"] == '{"text": "hi there"}'

def test_rest_response_mapping():
    config = {
        "endpoint": "http://example.com/api",
        "request_mapping": {"message_field": "msg"},
        "response_mapping": {"reply_field": "data.reply"}
    }
    adapter = RestChatAdapter(config)
    with patch("requests.request") as mock_req:
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"reply": "got it"}}
        mock_req.return_value = mock_response
        
        reply = adapter.send_message("test")
        assert reply == "got it"

def test_gemini_request_body_generation_and_history():
    config = {
        "endpoint": "http://example.com/api",
        "request_mapping": {
            "history_field": "contents",
            "history_item_template": {
                "role": "{{role}}",
                "parts": [{"text": "{{content}}"}]
            },
            "history_role_map": {
                "user": "user",
                "agent": "model",
                "simulated_user": "user"
            }
        },
        "response_mapping": {
            "reply_field": "candidates.0.content.parts.0.text"
        }
    }
    adapter = RestChatAdapter(config)
    
    # Simulate an existing turn
    adapter.transcript.append(ConversationMessage(role="agent", content="first agent reply", turn_index=0, timestamp=""))
    
    with patch("requests.request") as mock_req:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "gemini reply"}]}}]
        }
        mock_req.return_value = mock_response
        
        reply = adapter.send_message("second user message")
        
        assert reply == "gemini reply"
        kwargs = mock_req.call_args.kwargs
        contents = kwargs["json"]["contents"]
        assert len(contents) == 2
        assert contents[0]["role"] == "model"
        assert contents[0]["parts"][0]["text"] == "first agent reply"
        assert contents[1]["role"] == "user"
        assert contents[1]["parts"][0]["text"] == "second user message"

def test_gemini_api_key_resolution():
    with patch.dict(os.environ, {"MY_TEST_KEY": "secret123"}):
        config = {
            "endpoint": "http://example.com/api",
            "headers": {
                "x-goog-api-key": "env:MY_TEST_KEY"
            },
            "request_mapping": {"message_field": "msg"},
            "response_mapping": {"reply_field": "reply"}
        }
        adapter = RestChatAdapter(config)
        assert adapter.headers["x-goog-api-key"] == "secret123"

def test_gemini_http_400_error_handling():
    with patch.dict(os.environ, {"MY_TEST_KEY": "secret123"}):
        config = {
            "endpoint": "http://example.com/api",
            "headers": {"x-goog-api-key": "env:MY_TEST_KEY"},
            "request_mapping": {"message_field": "msg"},
            "response_mapping": {"reply_field": "reply"}
        }
        adapter = RestChatAdapter(config)
        with patch("requests.request") as mock_req:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.text = '{"error": {"message": "Invalid argument secret123 provided"}}'
            mock_response.json.return_value = {"error": {"message": "Invalid argument secret123 provided"}}
            
            http_err = requests.exceptions.HTTPError()
            http_err.response = mock_response
            mock_response.raise_for_status.side_effect = http_err
            
            mock_req.return_value = mock_response
            
            with pytest.raises(ValueError) as exc:
                adapter.send_message("test")
            
            # Key should be redacted
            assert "secret123" not in str(exc.value)
            assert "***REDACTED***" in str(exc.value)
            assert "Invalid argument" in str(exc.value)

def test_scenario_validation_endpoint():
    valid_yaml = """
scenario_id: test_scenario
agent:
  channel: chatbot
persona:
  name: Tester
  goal: Test the system
  tone: Helpful
max_turns: 5
"""
    res = client.post("/scenarios/validate", json={"yaml_text": valid_yaml})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

def test_scenario_validation_endpoint_invalid_schema():
    invalid_yaml = """
scenario_id: test_scenario
agent:
  channel: chatbot
# missing persona
"""
    res = client.post("/scenarios/validate", json={"yaml_text": invalid_yaml})
    assert res.status_code == 400
    assert "persona" in res.json()["detail"]

def test_scenario_validation_endpoint_invalid_yaml():
    res = client.post("/scenarios/validate", json={"yaml_text": "this: is: not: valid: yaml"})
    assert res.status_code == 400
    assert "Invalid YAML" in res.json()["detail"]

def test_scenario_save_endpoint(tmp_path):
    with patch("app.main._SCENARIOS_DIR", tmp_path):
        valid_yaml = """
scenario_id: save_test
agent:
  channel: chatbot
persona:
  name: Saver
  goal: Save the file properly
  tone: Fast
"""
        res = client.post("/scenarios/save", json={
            "filename": "save_test.yaml",
            "yaml_text": valid_yaml
        })
        if res.status_code != 200:
            print(res.json())
        assert res.status_code == 200
        assert (tmp_path / "save_test.yaml").exists()

def test_scenario_save_duplicate(tmp_path):
    with patch("app.main._SCENARIOS_DIR", tmp_path):
        valid_yaml = """
scenario_id: save_test
agent:
  channel: chatbot
persona:
  name: Saver
  goal: Save the file properly
  tone: Fast
"""
        (tmp_path / "save_test.yaml").write_text("existing")
        
        # Should fail without force
        res = client.post("/scenarios/save", json={
            "filename": "save_test.yaml",
            "yaml_text": valid_yaml
        })
        if res.status_code != 409:
            print(res.json())
        assert res.status_code == 409
        
        # Should succeed with force
        res2 = client.post("/scenarios/save", json={
            "filename": "save_test.yaml",
            "yaml_text": valid_yaml,
            "force": True
        })
        assert res2.status_code == 200

def test_scenario_save_path_traversal(tmp_path):
    with patch("app.main._SCENARIOS_DIR", tmp_path):
        res = client.post("/scenarios/save", json={
            "filename": "../secret.yaml",
            "yaml_text": "scenario_id: test\nagent:\n  channel: chatbot\npersona:\n  name: Test\n  goal: Test\n  tone: Test"
        })
        assert res.status_code == 400
        assert "Invalid filename" in res.json()["detail"]
