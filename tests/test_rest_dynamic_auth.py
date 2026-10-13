import os
import json
import pytest
from unittest.mock import patch, MagicMock
from app.adapters.chat.rest import RestChatAdapter

@pytest.fixture
def temp_storage_state(tmp_path):
    state = {
        "cookies": [
            {"name": "__session", "value": "mock_jwt_session"}
        ]
    }
    p = tmp_path / "storage_state.json"
    p.write_text(json.dumps(state))
    return str(p)

def test_dynamic_rest_auth(temp_storage_state):
    config = {
        "endpoint": "http://api.target.com/ask",
        "auth": {
            "type": "dynamic_rest",
            "storage_state": temp_storage_state,
            "steps": [
                {
                    "url": "http://auth.target.com/client",
                    "method": "GET",
                    "extract": {
                        "sess_id": "response.sessions.0.id"
                    }
                },
                {
                    "url": "http://auth.target.com/client/sessions/{sess_id}/tokens",
                    "method": "POST",
                    "extract_token": "jwt"
                }
            ]
        }
    }
    
    with patch('requests.request') as mock_req:
        def side_effect(method, url, **kwargs):
            mock_res = MagicMock()
            if "client/sessions" in url:
                mock_res.json.return_value = {"jwt": "fresh_jwt_token_123"}
            else:
                mock_res.json.return_value = {"response": {"sessions": [{"id": "session_123"}]}}
            mock_res.raise_for_status = MagicMock()
            return mock_res
            
        mock_req.side_effect = side_effect
        
        adapter = RestChatAdapter(config)
        assert adapter.headers.get("Authorization") == "Bearer fresh_jwt_token_123"
        assert mock_req.call_count == 2
        
        call1 = mock_req.call_args_list[0]
        assert call1[0][1] == "http://auth.target.com/client"
        assert call1[1]["cookies"]["__session"] == "mock_jwt_session"
        
        call2 = mock_req.call_args_list[1]
        assert call2[0][1] == "http://auth.target.com/client/sessions/session_123/tokens"

def test_dynamic_rest_auth_failure_throws(temp_storage_state):
    config = {
        "endpoint": "http://api.target.com/ask",
        "auth": {
            "type": "dynamic_rest",
            "storage_state": temp_storage_state,
            "steps": [
                {
                    "url": "http://auth.target.com/client",
                    "method": "GET",
                    "extract": {
                        "sess_id": "response.sessions.0.id"
                    }
                }
            ]
        }
    }
    
    with patch('requests.request') as mock_req:
        mock_res = MagicMock()
        mock_res.json.return_value = {"response": {"sessions": []}}
        mock_res.raise_for_status = MagicMock()
        mock_req.return_value = mock_res
        
        with pytest.raises(ValueError, match="Failed to extract dynamic token from steps"):
            RestChatAdapter(config)
