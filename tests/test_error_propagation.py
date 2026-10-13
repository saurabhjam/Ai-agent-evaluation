import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.connection import AgentConnection, AgentType
from app.connections.storage import repository
from app.adapters.chat.base import ChatAdapter
from app.connections.manager import ConnectionManager

class DummyCrashingAdapter(ChatAdapter):
    def __init__(self, config):
        pass
    def connect(self):
        # Using NotImplementedError because its str() is empty by default, 
        # which perfectly reproduces the bug where the message was lost.
        raise NotImplementedError("This is a synthetic crash string")
    def send_message(self, message, agent_prompt=None, attachments=None):
        pass
    def get_transcript(self):
        return []
    def get_conversation(self):
        pass
    def close(self):
        pass

def test_error_propagation_through_api(monkeypatch):
    monkeypatch.setattr(ConnectionManager, "create_adapter", lambda self, conn: DummyCrashingAdapter(conn.config))
    
    # Create a test connection
    conn = AgentConnection(
        id="crash-test-id",
        name="Crash Test",
        type=AgentType.chatbot,
        adapter="crashing_adapter",
        config={}
    )
    repository.save(conn)
    
    # Create a dummy scenario file temporarily
    import tempfile
    import yaml
    import os
    
    scen = {
        "scenario_id": "test_scenario",
        "agent": {"channel": "chatbot"},
        "persona": {"name": "Test", "role": "Test", "goal": "This is a long valid goal", "tone": "Test"},
        "max_turns": 2,
        "evaluation": {"metrics": []}
    }
    
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, 'w') as f:
        yaml.dump(scen, f)
        
    try:
        client = TestClient(app)
        response = client.post(
            f"/connections/{conn.id}/evaluate",
            json={"scenario_path": path}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is False
        
        # The error MUST contain the exception type and the synthetic crash string
        assert "NotImplementedError" in data["error"]
        assert "This is a synthetic crash string" in data["error"]
        
    finally:
        os.remove(path)
