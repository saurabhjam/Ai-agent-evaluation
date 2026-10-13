import pytest

from app.connections.input import AgentConnectionInput, AuthConfig, ConnectionConfig
from app.connections.parser import parse_connection_input


def _input(options):
    return AgentConnectionInput(
        name="Browser Token REST",
        type="chatbot",
        connection=ConnectionConfig(
            method="rest",
            url="https://api.example.test/ask",
            auth=AuthConfig(type="browser_token", value="browser_token"),
            options={"browser_login_url": "https://app.example.test", **options},
        ),
    )


def test_parse_browser_token_accepts_network_strategy():
    conn = parse_connection_input(_input({"intercept_pattern": "*/tokens*", "token_path": "jwt"}))
    assert conn.config["auth"]["intercept_pattern"] == "*/tokens*"
    assert conn.config["auth"]["token_path"] == "jwt"


def test_parse_browser_token_accepts_script_strategy_without_network_fields():
    conn = parse_connection_input(_input({"script": "window.Clerk.session.getToken()"}))
    assert conn.config["auth"]["script"] == "window.Clerk.session.getToken()"
    assert "intercept_pattern" not in conn.config["auth"]
    assert "token_path" not in conn.config["auth"]


def test_parse_browser_token_rejects_empty_strategy():
    with pytest.raises(ValueError, match="requires either a script"):
        parse_connection_input(_input({}))


def test_parse_browser_token_rejects_intercept_only():
    with pytest.raises(ValueError, match="token_path is required"):
        parse_connection_input(_input({"intercept_pattern": "*/tokens*"}))


def test_parse_browser_token_rejects_token_path_only():
    with pytest.raises(ValueError, match="intercept_pattern is required"):
        parse_connection_input(_input({"token_path": "jwt"}))
