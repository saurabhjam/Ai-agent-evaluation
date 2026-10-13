import os
import pytest
from app.adapters.chat.browser import BrowserChatAdapter
from app.models.connection import AgentConnection, AgentType
from app.executor import ScenarioExecutor
from app.schemas import TestScenario, Persona, AgentConfig

def test_browser_spa_readiness():
    fixture_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures", "test_chat_spa.html"))
    safe_path = fixture_path.replace("\\", "/")
    file_url = f"file:///{safe_path}"
    
    config = {
        "url": file_url,
        "browser": {
            "headless": True,
            "timeout_ms": 10000
        },
        "selectors": {
            "input": "#chat-input",
            "submit": "#chat-submit",
            "response": ".msg.agent"
        },
        "interaction": {
            "submit_mode": "click",
            "response_timeout_ms": 5000
        }
    }
    
    adapter = BrowserChatAdapter(config)
    try:
        # connect should wait for the SPA to inject #chat-input before completing
        adapter.connect()
        
        # message should be sent successfully
        resp1 = adapter.send_message("Hello")
        assert resp1 == "SPA Response"
    finally:
        adapter.close()


def test_browser_redirect_login():
    fixture_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures", "login.html"))
    safe_path = fixture_path.replace("\\", "/")
    file_url = f"file:///{safe_path}"
    
    config = {
        "url": file_url,
        "browser": {
            "headless": True,
            "timeout_ms": 10000
        },
        "selectors": {
            "input": "#chat-input",
            "submit": "#chat-submit",
            "response": ".msg.agent"
        },
        "interaction": {
            "submit_mode": "click",
            "response_timeout_ms": 5000
        }
    }
    
    adapter = BrowserChatAdapter(config)
    try:
        with pytest.raises(ValueError, match="Browser authentication state is not valid or the target redirected to login"):
            adapter.connect()
    finally:
        adapter.close()

def test_browser_storage_state_config_inheritance():
    # Test that ScenarioExecutor passes down storage_state from connection config
    conn = AgentConnection(
        id="test-conn",
        name="Test",
        type=AgentType.chatbot,
        adapter="browser",
        enabled=True,
        config={
            "url": "http://example.com",
            "storage_state": "test_auth.json",
            "selectors": {
                "input": "#in",
                "response": "#out"
            }
        }
    )
    
    scenario = TestScenario(
        scenario_id="scenario1",
        agent=AgentConfig(channel="chatbot", adapter="browser"),
        persona=Persona(name="testp", system_prompt="test", goal="buy something", tone="polite"),
        max_turns=2
    )
    
    executor = ScenarioExecutor()
    adapter = executor.manager.create_adapter(conn)
    
    # We inspect the adapter to ensure storage_state is there
    assert adapter.config.get("storage_state") == "test_auth.json"
