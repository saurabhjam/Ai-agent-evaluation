import pytest
import base64
import json
import time
from unittest.mock import patch, MagicMock
from app.adapters.chat.rest import RestChatAdapter


def _unsigned_jwt(*, iat: int, exp: int) -> str:
    def enc(data):
        raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{enc({'alg': 'none'})}.{enc({'iat': iat, 'exp': exp})}.sig"

def test_browser_token_auth_success():
    config = {
        "endpoint": "http://api.target.com/ask",
        "auth": {
            "type": "browser_token",
            "url": "http://target.com",
            "intercept_pattern": "*/tokens",
            "token_path": "jwt",
            "storage_state": "dummy.json"
        }
    }
    
    with patch('app.connections.browser_auth.browser_auth_manager.extract_browser_token_sync') as mock_extract:
        mock_extract.return_value = "fresh_jwt_token_456"
        
        adapter = RestChatAdapter(config)
        
        assert adapter.headers.get("Authorization") == "Bearer fresh_jwt_token_456"
        mock_extract.assert_called_once_with(
            url="http://target.com",
            storage_state="dummy.json",
            script=None,
            intercept_pattern="*/tokens",
            token_path="jwt",
            trigger_script=None,
            delete_cookies=None,
            strategy="network",
        )


def test_browser_token_auth_script_success_without_network_config():
    config = {
        "endpoint": "http://api.target.com/ask",
        "auth": {
            "type": "browser_token",
            "url": "http://target.com",
            "script": "window.Clerk.session.getToken()",
            "storage_state": "dummy.json",
            "header_name": "Authorization",
            "header_format": "Bearer {token}",
        }
    }

    with patch("app.connections.browser_auth.browser_auth_manager.extract_browser_token_sync") as mock_extract:
        mock_extract.return_value = "script_jwt"

        adapter = RestChatAdapter(config)

        assert adapter.headers.get("Authorization") == "Bearer script_jwt"
        mock_extract.assert_called_once_with(
            url="http://target.com",
            storage_state="dummy.json",
            script="window.Clerk.session.getToken()",
            intercept_pattern=None,
            token_path=None,
            trigger_script=None,
            delete_cookies=None,
            strategy="script",
        )


def test_browser_token_script_strategy_ignores_legacy_network_values():
    config = {
        "endpoint": "http://api.target.com/ask",
        "auth": {
            "type": "browser_token",
            "url": "http://target.com",
            "script": "window.Clerk.session.getToken()",
            "intercept_pattern": "*/tokens",
            "token_path": "jwt",
        }
    }

    with patch("app.connections.browser_auth.browser_auth_manager.extract_browser_token_sync") as mock_extract:
        mock_extract.return_value = "script_jwt"

        RestChatAdapter(config)

        call = mock_extract.call_args.kwargs
        assert call["strategy"] == "script"
        assert call["intercept_pattern"] is None
        assert call["token_path"] is None


def test_legacy_sophia_connection_uses_backend_authorization_header_capture():
    config = {
        "endpoint": "https://tribe-gateway.archietech.co/owners/api/v1/admin/sophia/ask",
        "storage_state": "auth-state-Sophia_Ai.json",
        "auth": {
            "type": "browser_token",
            "value": "browser_token",
            "url": "https://dev.pms.jointribex.com/sophia",
            "script": "window.Clerk && window.Clerk.session ? window.Clerk.session.getToken() : null",
            "intercept_pattern": "*://clerk.dev.pms.jointribex.com/v1/client/sessions/*/tokens*",
            "token_path": "jwt",
            "header_name": "Authorization",
            "header_format": "Bearer {token}",
        },
    }

    with patch("app.connections.browser_auth.browser_auth_manager.extract_browser_token_sync") as mock_extract:
        mock_extract.return_value = "captured_sophia_authorization"

        adapter = RestChatAdapter(config)

        assert adapter.headers.get("Authorization") == "Bearer captured_sophia_authorization"
        mock_extract.assert_called_once_with(
            url="https://dev.pms.jointribex.com/sophia",
            storage_state="auth-state-Sophia_Ai.json",
            script=None,
            intercept_pattern="*://tribe-gateway.archietech.co/owners/api/v1/admin/*",
            token_path="header:authorization",
            trigger_script=None,
            delete_cookies=None,
            strategy="network",
        )

def test_browser_token_auth_failure_throws():
    config = {
        "endpoint": "http://api.target.com/ask",
        "auth": {
            "type": "browser_token",
            "url": "http://target.com",
            "intercept_pattern": "*/tokens",
            "token_path": "jwt"
        }
    }
    
    with patch('app.connections.browser_auth.browser_auth_manager.extract_browser_token_sync') as mock_extract:
        mock_extract.return_value = None
        
        with pytest.raises(ValueError, match="Failed to extract browser token"):
            RestChatAdapter(config)


def test_browser_token_network_mode_requires_both_fields():
    with pytest.raises(ValueError, match="missing token_path"):
        RestChatAdapter({
            "endpoint": "http://api.target.com/ask",
            "auth": {
                "type": "browser_token",
                "url": "http://target.com",
                "intercept_pattern": "*/tokens",
            }
        })

    with pytest.raises(ValueError, match="missing intercept_pattern"):
        RestChatAdapter({
            "endpoint": "http://api.target.com/ask",
            "auth": {
                "type": "browser_token",
                "url": "http://target.com",
                "token_path": "jwt",
            }
        })


def test_existing_non_browser_token_auth_modes_unchanged(monkeypatch):
    monkeypatch.setenv("TEST_TOKEN", "token456")
    adapter = RestChatAdapter(config={
        "endpoint": "http://test",
        "auth": {
            "type": "bearer",
            "value": "env:TEST_TOKEN"
        }
    })
    assert adapter.headers.get("Authorization") == "Bearer token456"


def test_browser_token_refreshes_only_when_expiring_before_send_message():
    now = int(time.time())
    expired = _unsigned_jwt(iat=now - 120, exp=now - 1)
    fresh = _unsigned_jwt(iat=now, exp=now + 120)
    config = {
        "endpoint": "http://api.target.com/ask",
        "auth": {
            "type": "browser_token",
            "url": "http://target.com",
            "intercept_pattern": "*/tokens",
            "token_path": "jwt",
            "storage_state": "dummy.json",
        },
        "request_mapping": {"message_field": "message"},
        "response_mapping": {"reply_field": "reply"},
    }

    response = MagicMock()
    response.status_code = 200
    response.text = '{"reply":"ok"}'
    response.json.return_value = {"reply": "ok"}
    response.raise_for_status.return_value = None

    with patch("app.connections.browser_auth.browser_auth_manager.extract_browser_token_sync") as mock_extract, \
         patch("app.adapters.chat.rest.requests.request", return_value=response) as mock_request:
        mock_extract.side_effect = [expired, fresh]

        adapter = RestChatAdapter(config)
        reply = adapter.send_message("hello")

    assert reply == "ok"
    assert mock_extract.call_count == 2
    sent_headers = mock_request.call_args.kwargs["headers"]
    assert sent_headers["Authorization"] == f"Bearer {fresh}"
