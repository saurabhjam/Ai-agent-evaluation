import os
import pytest
from app.models.connection import AgentConnection, AgentType
from app.connections.storage import ConnectionRepository
from app.config import settings

def test_persistence_generic():
    # Use the test db path or the actual configured one for tests
    repo = ConnectionRepository()
    
    # 1. Create a REST connection
    rest_conn = AgentConnection(
        id="test-rest-conn",
        name="REST Test",
        type=AgentType.chatbot,
        adapter="rest",
        config={
            "url": "http://example.com/api",
            "auth": {"type": "api_key", "value": "env:MY_API_KEY"}
        }
    )
    repo.save(rest_conn)
    
    # 2. Create a Browser connection with selectors
    browser_conn = AgentConnection(
        id="test-browser-conn",
        name="Browser Test",
        type=AgentType.chatbot,
        adapter="browser",
        config={
            "url": "http://example.com/demo",
            "selectors": {
                "input": "#in",
                "submit": "#sub",
                "response": "#res"
            }
        }
    )
    repo.save(browser_conn)
    
    # 3. Create a Voice connection
    voice_conn = AgentConnection(
        id="test-voice-conn",
        name="Voice Test",
        type=AgentType.voice,
        adapter="livekit",
        config={
            "url": "wss://example.livekit.cloud",
            "auth": {"type": "api_key", "value": "env:LIVEKIT_API_KEY"}
        }
    )
    repo.save(voice_conn)
    
    # Simulate a backend restart by creating a completely new repository instance
    new_repo = ConnectionRepository()
    
    # 4. Verify REST is preserved
    loaded_rest = new_repo.get("test-rest-conn")
    assert loaded_rest is not None
    assert loaded_rest.id == "test-rest-conn"
    assert loaded_rest.adapter == "rest"
    assert loaded_rest.config["url"] == "http://example.com/api"
    assert loaded_rest.config["auth"]["value"] == "env:MY_API_KEY"
    
    # 5. Verify Browser is preserved
    loaded_browser = new_repo.get("test-browser-conn")
    assert loaded_browser is not None
    assert loaded_browser.config["selectors"]["input"] == "#in"
    
    # 6. Verify Voice is preserved
    loaded_voice = new_repo.get("test-voice-conn")
    assert loaded_voice is not None
    assert loaded_voice.adapter == "livekit"
    assert loaded_voice.config["url"] == "wss://example.livekit.cloud"
    
    # 7. Delete and verify persistence of delete
    assert new_repo.delete("test-rest-conn") is True
    
    # Restart again
    third_repo = ConnectionRepository()
    assert third_repo.get("test-rest-conn") is None
    assert third_repo.get("test-browser-conn") is not None
