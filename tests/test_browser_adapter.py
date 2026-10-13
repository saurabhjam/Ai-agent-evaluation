import os
import pytest
from app.adapters.chat.browser import BrowserChatAdapter
from app.models.conversation import ConversationMessage

def test_missing_url():
    with pytest.raises(ValueError, match="Browser adapter requires: url"):
        BrowserChatAdapter({
            "selectors": {"input": "#in", "response": "#out"}
        })

def test_missing_input_selector():
    with pytest.raises(ValueError, match="Browser adapter requires: selectors.input"):
        BrowserChatAdapter({
            "url": "http://test",
            "selectors": {"response": "#out"}
        })

def test_missing_response_selector():
    with pytest.raises(ValueError, match="Browser adapter requires: selectors.response"):
        BrowserChatAdapter({
            "url": "http://test",
            "selectors": {"input": "#in"}
        })

def test_browser_adapter_e2e():
    fixture_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures", "test_chat.html"))
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
        adapter.connect()
        
        # Turn 1
        resp1 = adapter.send_message("Hello")
        assert resp1 == "Hello! How can I help?"
        
        # Turn 2
        resp2 = adapter.send_message("I want to return a product.")
        assert resp2 == "I can help you with that."
        
        # Turn 3
        resp3 = adapter.send_message("Blah")
        assert resp3 == "I don't understand."
        
        # Verify transcript
        transcript = adapter.get_transcript()
        assert len(transcript) == 6
        assert transcript[0].role == "simulated_user"
        assert transcript[0].content == "Hello"
        assert transcript[1].role == "agent"
        assert transcript[1].content == "Hello! How can I help?"
        
        assert transcript[4].role == "simulated_user"
        assert transcript[4].content == "Blah"
        assert transcript[5].role == "agent"
        assert transcript[5].content == "I don't understand."
        
    finally:
        adapter.close()

def test_browser_adapter_launcher_e2e():
    fixture_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'fixtures', 'test_chat_launcher.html'))
    safe_path = fixture_path.replace('\\\\', '/')
    file_url = f'file:///{safe_path}'
    
    config = {
        'url': file_url,
        'browser': {
            'headless': True,
            'timeout_ms': 10000
        },
        'selectors': {
            'input': '#chat-input',
            'submit': '#chat-submit',
            'response': '.msg.agent',
            'launcher': '#launcher'
        },
        'interaction': {
            'submit_mode': 'click',
            'response_timeout_ms': 5000
        }
    }
    
    adapter = BrowserChatAdapter(config)
    try:
        adapter.connect()
        
        # Turn 1
        resp1 = adapter.send_message('Hello')
        assert resp1 == 'Hello! How can I help?'
    finally:
        adapter.close()

