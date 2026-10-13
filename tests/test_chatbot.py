import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from unittest.mock import patch
import uuid
import requests

client = TestClient(app)

def test_mock_chat_valid_request_response():
    session_id = str(uuid.uuid4())
    payload = {"session_id": session_id, "message": "I need a refund for A1029"}
    
    with patch("requests.post") as mock_post:
        mock_response = requests.Response()
        mock_response.status_code = 200
        mock_response._content = b'{"message": {"content": "I have processed a full refund for A1029."}}'
        mock_post.return_value = mock_response
        
        response = client.post("/mock-chat", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "reply" in data
        assert "refund" in data["reply"].lower()

def test_mock_chat_session_id_handling():
    # Test that it requires session_id
    response = client.post("/mock-chat", json={"message": "hello"})
    assert response.status_code == 422 # Validation error missing session_id

def test_mock_chat_custom_agent_prompt():
    session_id = str(uuid.uuid4())
    payload = {
        "session_id": session_id,
        "message": "I need a refund for A1029",
        "agent_prompt": "You are a test agent."
    }
    
    with patch("requests.post") as mock_post:
        mock_response = requests.Response()
        mock_response.status_code = 200
        mock_response._content = b'{"message": {"content": "I have processed a full refund for A1029."}}'
        mock_post.return_value = mock_response
        
        response = client.post("/mock-chat", json=payload)
        assert response.status_code == 200
        
        # Verify that the system prompt sent to Ollama is the custom one
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["messages"][0]["role"] == "system"
        assert kwargs["json"]["messages"][0]["content"] == "You are a test agent."

def test_mock_chat_system_prompt_not_duplicated():
    session_id = str(uuid.uuid4())
    payload = {"session_id": session_id, "message": "hello"}
    
    with patch("requests.post") as mock_post:
        mock_response = requests.Response()
        mock_response.status_code = 200
        mock_response._content = b'{"message": {"content": "reply"}}'
        mock_post.return_value = mock_response
        
        client.post("/mock-chat", json=payload)
        client.post("/mock-chat", json=payload)
        
        args, kwargs = mock_post.call_args
        
        # Check that there is exactly one system prompt in the messages payload
        system_prompts = [m for m in kwargs["json"]["messages"] if m["role"] == "system"]
        assert len(system_prompts) == 1

def test_mock_chat_seeded_defect():
    session_id = str(uuid.uuid4())
    settings.defect_generic_greeting_loop = True
    try:
        payload = {"session_id": session_id, "message": "I need a refund for A1029"}
        response = client.post("/mock-chat", json=payload)
        assert response.status_code == 200
        assert response.json()["reply"] == "Hello! I am the customer support bot. How can I help you today?"
    finally:
        settings.defect_generic_greeting_loop = False

def test_fake_adapter():
    from app.adapters.chat.fake import FakeChatAdapter
    adapter = FakeChatAdapter({"endpoint": "http://localhost:8000/mock-chat"})
    
    with patch("requests.post") as mock_post:
        mock_response = requests.Response()
        mock_response.status_code = 200
        mock_response._content = b'{"reply": "mocked response"}'
        mock_post.return_value = mock_response
        
        adapter.send_message("Hello")
        
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "http://localhost:8000/mock-chat"
        assert kwargs["json"]["message"] == "Hello"
        assert kwargs["json"]["session_id"] == adapter.session_id

def test_rest_adapter():
    from app.adapters.chat.rest import RestChatAdapter
    adapter = RestChatAdapter({
        "endpoint": "http://localhost:8080/chat",
        "request_mapping": {
            "session_id_field": "session_id",
            "message_field": "message"
        }
    })
    
    with patch("requests.request") as mock_req:
        mock_response = requests.Response()
        mock_response.status_code = 200
        mock_response._content = b'{"reply": "real response"}'
        mock_req.return_value = mock_response
        
        adapter.send_message("Hello")
        
        mock_req.assert_called_once()
        args, kwargs = mock_req.call_args
        assert kwargs["url"] == "http://localhost:8080/chat"
        assert kwargs["json"]["message"] == "Hello"
        assert kwargs["json"]["session_id"] == adapter.session_id

from app.simulator import generate_next_user_turn
from app.schemas import Persona
from app.models.conversation import ConversationMessage

def test_simulator_groq_integration():
    persona = Persona(name="Bob", goal="I want a refund for my order", tone="angry", edge_case="")
    transcript = [ConversationMessage(turn_index=1, role="agent", content="Hello")]
    
    with patch("app.simulator.Groq") as mock_groq_class:
        mock_client = mock_groq_class.return_value
        mock_client.chat.completions.create.return_value.choices[0].message.content = "I want a refund!"
        
        reply = generate_next_user_turn(persona, transcript)

        assert isinstance(reply, dict)
        assert reply["message"] == "I want a refund!"
        mock_groq_class.assert_called_once()
        mock_client.chat.completions.create.assert_called_once()
        
        # Verify the exact parameters passed to Groq
        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs.get("reasoning_effort") == "low"
        assert kwargs.get("include_reasoning") is False
        assert kwargs.get("max_completion_tokens") == 256

def test_simulator_groq_empty_response():
    persona = Persona(name="Bob", goal="I want a refund for my order", tone="angry", edge_case="")
    transcript = [ConversationMessage(turn_index=1, role="agent", content="Hello")]
    
    with patch("app.simulator.Groq") as mock_groq_class:
        mock_client = mock_groq_class.return_value
        # Simulate empty content due to reasoning token budget exhaustion
        mock_client.chat.completions.create.return_value.choices[0].message.content = ""
        
        with pytest.raises(RuntimeError, match="Groq returned empty content"):
            generate_next_user_turn(persona, transcript)
