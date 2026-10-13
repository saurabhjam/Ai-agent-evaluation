import pytest
from unittest.mock import patch
from app.connections.input import AgentConnectionInput, ConnectionConfig, AuthConfig
from app.connections.parser import parse_connection_input
from app.adapters.chat.rest import RestChatAdapter
from app.models.connection import AgentConnection

def test_missing_intercept_pattern_rejected():
    with pytest.raises(ValueError, match="missing intercept_pattern"):
        parse_connection_input(
            AgentConnectionInput(
                name="Test",
                type="chatbot",
                connection=ConnectionConfig(
                    method="browser",
                    url="http://test",
                    auth=AuthConfig(type="browser_token", value="browser_token"),
                    options={"token_path": "test"}
                )
            )
        )

def test_missing_token_path_rejected():
    with pytest.raises(ValueError, match="missing token_path"):
        parse_connection_input(
            AgentConnectionInput(
                name="Test",
                type="chatbot",
                connection=ConnectionConfig(
                    method="browser",
                    url="http://test",
                    auth=AuthConfig(type="browser_token", value="browser_token"),
                    options={"intercept_pattern": "test"}
                )
            )
        )

def test_complete_configuration_accepted():
    conn = parse_connection_input(
        AgentConnectionInput(
            name="Test",
            type="chatbot",
            connection=ConnectionConfig(
                method="browser",
                url="http://test",
                auth=AuthConfig(type="browser_token", value="browser_token"),
                options={"intercept_pattern": "*/tokens", "token_path": "data.token"}
            )
        )
    )
    assert conn.config["auth"]["intercept_pattern"] == "*/tokens"
    assert conn.config["auth"]["token_path"] == "data.token"

def test_legacy_incomplete_connection_produces_clear_configuration_error_before_playwright_launches():
    config = {
        "endpoint": "http://api.target.com/ask",
        "auth": {
            "type": "browser_token",
            "url": "http://target.com"
            # Missing intercept_pattern and token_path
        }
    }
    with patch('app.connections.browser_auth.browser_auth_manager.extract_browser_token_sync') as mock_extract:
        with pytest.raises(ValueError, match="Browser token authentication is incomplete: missing intercept_pattern and token_path."):
            RestChatAdapter(config)
        mock_extract.assert_not_called()

def test_legacy_incomplete_connection_missing_token_path():
    config = {
        "endpoint": "http://api.target.com/ask",
        "auth": {
            "type": "browser_token",
            "url": "http://target.com",
            "intercept_pattern": "*/tokens"
            # Missing token_path
        }
    }
    with patch('app.connections.browser_auth.browser_auth_manager.extract_browser_token_sync') as mock_extract:
        with pytest.raises(ValueError, match="Browser token authentication is incomplete: missing token_path."):
            RestChatAdapter(config)
        mock_extract.assert_not_called()

def test_header_defaults_preserved():
    config = {
        "endpoint": "http://api.target.com/ask",
        "auth": {
            "type": "browser_token",
            "url": "http://target.com",
            "intercept_pattern": "*/tokens",
            "token_path": "token"
        }
    }
    with patch('app.connections.browser_auth.browser_auth_manager.extract_browser_token_sync') as mock_extract:
        mock_extract.return_value = "mytoken"
        adapter = RestChatAdapter(config)
        assert adapter.headers.get("Authorization") == "Bearer mytoken"

def test_existing_non_browser_token_auth_modes_unaffected():
    config = {
        "endpoint": "http://api.target.com/ask",
        "auth": {
            "type": "bearer",
            "value": "mybearer"
        }
    }
    adapter = RestChatAdapter(config)
    assert adapter.headers.get("Authorization") == "Bearer mybearer"

def test_valid_storage_state_does_not_falsely_imply_token_configuration_is_complete():
    # If storage_state exists, it should still fail if intercept_pattern is missing
    config = {
        "endpoint": "http://api.target.com/ask",
        "auth": {
            "type": "browser_token",
            "url": "http://target.com",
            "storage_state": "state.json"
        }
    }
    with patch('app.connections.browser_auth.browser_auth_manager.extract_browser_token_sync') as mock_extract:
        with pytest.raises(ValueError, match="Browser token authentication is incomplete: missing intercept_pattern."):
            RestChatAdapter(config)
