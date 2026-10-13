"""
Unit tests for Phase 3 — Client-facing Connection Input / Onboarding Layer.

Test coverage
─────────────
 1.  Generic chatbot REST input
 2.  Generic chatbot WebSocket input
 3.  Generic chatbot Browser input
 4.  Generic voice LiveKit input
 5.  Invalid type
 6.  Missing name
 7.  Missing connection method
 8.  Unsupported method (completely unknown)
 9.  Chatbot + voice-only method mismatch
10.  Voice + chatbot-only method mismatch
11.  Generic authentication (api_key and bearer)
12.  Options/config passthrough
13.  Secrets not exposed in any surface (repr, str, result, error)
14.  Input successfully converted to AgentConnection
15.  connect_and_test() calls ConnectionManager
16.  ConnectionTestResult is returned
17.  Existing adapters are not modified (import smoke test)

Design rules
─────────────
- NO real external services.
- NO real credentials.  All fake secrets are clearly labelled.
- Existing Phase 2 tests (test_connection_manager.py) are not modified.
- Existing adapter code is imported read-only to confirm it is unchanged.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from pydantic import ValidationError

from app.connections.input import (
    AgentConnectionInput,
    AuthConfig,
    ChatbotMethod,
    ConnectionConfig,
    VoiceMethod,
)
from app.connections.parser import connect_and_test, parse_connection_input
from app.connections.registry import AdapterRegistry
from app.connections.result import ConnectionStatus, ConnectionTestResult
from app.connections.manager import ConnectionManager
from app.models.connection import AgentConnection, AgentType


# ===========================================================================
# Helpers
# ===========================================================================

def _chatbot_rest_input(**overrides) -> AgentConnectionInput:
    defaults = dict(
        name="Test REST Chatbot",
        type="chatbot",
        connection=ConnectionConfig(method="rest", url="https://fake.example.test/chat"),
    )
    defaults.update(overrides)
    return AgentConnectionInput(**defaults)


def _chatbot_ws_input(**overrides) -> AgentConnectionInput:
    defaults = dict(
        name="Test WebSocket Chatbot",
        type="chatbot",
        connection=ConnectionConfig(method="websocket", url="wss://fake.example.test/ws"),
    )
    defaults.update(overrides)
    return AgentConnectionInput(**defaults)


def _chatbot_browser_input(**overrides) -> AgentConnectionInput:
    defaults = dict(
        name="Test Browser Chatbot",
        type="chatbot",
        connection=ConnectionConfig(method="browser", url="https://fake.example.test/chat"),
    )
    defaults.update(overrides)
    return AgentConnectionInput(**defaults)


def _voice_livekit_input(**overrides) -> AgentConnectionInput:
    defaults = dict(
        name="Test LiveKit Agent",
        type="voice",
        connection=ConnectionConfig(
            method="livekit",
            url="wss://fake-livekit.example.test",
            options={"agent_name": "test-agent"},
        ),
    )
    defaults.update(overrides)
    return AgentConnectionInput(**defaults)


def _mock_manager_connected(agent_id: str = "test-id") -> ConnectionManager:
    """Return a ConnectionManager whose test_connection() always returns connected."""
    manager = MagicMock(spec=ConnectionManager)
    manager.test_connection.return_value = ConnectionTestResult(
        success=True,
        status=ConnectionStatus.connected,
        agent_id=agent_id,
        adapter="rest",
        message="Connection successful.",
    )
    return manager


# ===========================================================================
# 1. Generic chatbot REST input
# ===========================================================================

class TestChatbotRestInput:
    def test_valid_rest_input_accepted(self):
        inp = _chatbot_rest_input()
        assert inp.name == "Test REST Chatbot"
        assert inp.type == "chatbot"
        assert inp.connection.method == "rest"
        assert inp.connection.url == "https://fake.example.test/chat"

    def test_rest_parses_to_agent_connection(self):
        inp = _chatbot_rest_input()
        conn = parse_connection_input(inp)
        assert isinstance(conn, AgentConnection)
        assert conn.type == AgentType.chatbot
        assert conn.adapter == "rest"
        assert conn.enabled is True

    def test_rest_url_in_config(self):
        inp = _chatbot_rest_input()
        conn = parse_connection_input(inp)
        # REST adapter expects base_url and endpoint
        assert conn.config.get("base_url") == "https://fake.example.test/chat"
        assert conn.config.get("endpoint") == "https://fake.example.test/chat"

    def test_rest_name_preserved(self):
        inp = _chatbot_rest_input()
        conn = parse_connection_input(inp)
        assert conn.name == "Test REST Chatbot"

    def test_rest_url_required(self):
        with pytest.raises(ValidationError, match="url"):
            AgentConnectionInput(
                name="No URL",
                type="chatbot",
                connection=ConnectionConfig(method="rest"),  # url omitted
            )


# ===========================================================================
# 2. Generic chatbot WebSocket input
# ===========================================================================

class TestChatbotWebSocketInput:
    def test_valid_websocket_input_accepted(self):
        inp = _chatbot_ws_input()
        assert inp.connection.method == "websocket"
        assert inp.connection.url == "wss://fake.example.test/ws"

    def test_websocket_parses_to_correct_adapter(self):
        inp = _chatbot_ws_input()
        conn = parse_connection_input(inp)
        assert conn.adapter == "websocket"
        assert conn.type == AgentType.chatbot

    def test_websocket_url_in_config(self):
        inp = _chatbot_ws_input()
        conn = parse_connection_input(inp)
        assert conn.config.get("base_url") == "wss://fake.example.test/ws"

    def test_websocket_url_required(self):
        with pytest.raises(ValidationError, match="url"):
            AgentConnectionInput(
                name="No URL WS",
                type="chatbot",
                connection=ConnectionConfig(method="websocket"),  # url omitted
            )


# ===========================================================================
# 3. Generic chatbot Browser input
# ===========================================================================

class TestChatbotBrowserInput:
    def test_valid_browser_input_accepted(self):
        inp = _chatbot_browser_input()
        assert inp.connection.method == "browser"
        assert inp.connection.url == "https://fake.example.test/chat"

    def test_browser_parses_to_correct_adapter(self):
        inp = _chatbot_browser_input()
        conn = parse_connection_input(inp)
        assert conn.adapter == "browser"
        assert conn.type == AgentType.chatbot

    def test_browser_url_in_config(self):
        inp = _chatbot_browser_input()
        conn = parse_connection_input(inp)
        assert conn.config.get("base_url") == "https://fake.example.test/chat"


# ===========================================================================
# 4. Generic voice LiveKit input
# ===========================================================================

class TestVoiceLiveKitInput:
    def test_valid_livekit_input_accepted(self):
        inp = _voice_livekit_input()
        assert inp.type == "voice"
        assert inp.connection.method == "livekit"
        assert inp.connection.url == "wss://fake-livekit.example.test"

    def test_livekit_parses_to_correct_adapter(self):
        inp = _voice_livekit_input()
        conn = parse_connection_input(inp)
        assert conn.adapter == "livekit"
        assert conn.type == AgentType.voice

    def test_livekit_url_in_config_under_server_url(self):
        inp = _voice_livekit_input()
        conn = parse_connection_input(inp)
        assert conn.config.get("server_url") == "wss://fake-livekit.example.test"

    def test_livekit_options_merged_into_config(self):
        inp = _voice_livekit_input()
        conn = parse_connection_input(inp)
        assert conn.config.get("agent_name") == "test-agent"

    def test_livekit_url_required(self):
        with pytest.raises(ValidationError, match="url"):
            AgentConnectionInput(
                name="No URL LiveKit",
                type="voice",
                connection=ConnectionConfig(method="livekit"),  # url omitted
            )


# ===========================================================================
# 5. Invalid type
# ===========================================================================

class TestInvalidType:
    def test_invalid_type_raises_validation_error(self):
        with pytest.raises(ValidationError, match="chatbot.*voice|type"):
            AgentConnectionInput(
                name="Bad Type",
                type="banking",          # not chatbot or voice
                connection=ConnectionConfig(method="rest", url="https://x.test"),
            )

    def test_another_invalid_type(self):
        with pytest.raises(ValidationError):
            AgentConnectionInput(
                name="Bad Type 2",
                type="customer_support",
                connection=ConnectionConfig(method="rest", url="https://x.test"),
            )

    def test_empty_type_raises_validation_error(self):
        with pytest.raises(ValidationError):
            AgentConnectionInput(
                name="Empty Type",
                type="",
                connection=ConnectionConfig(method="rest", url="https://x.test"),
            )


# ===========================================================================
# 6. Missing name
# ===========================================================================

class TestMissingName:
    def test_empty_name_raises_validation_error(self):
        with pytest.raises(ValidationError, match="name"):
            AgentConnectionInput(
                name="",
                type="chatbot",
                connection=ConnectionConfig(method="rest", url="https://x.test"),
            )

    def test_whitespace_only_name_raises_validation_error(self):
        with pytest.raises(ValidationError, match="name"):
            AgentConnectionInput(
                name="   ",
                type="chatbot",
                connection=ConnectionConfig(method="rest", url="https://x.test"),
            )


# ===========================================================================
# 7. Missing connection method
# ===========================================================================

class TestMissingConnectionMethod:
    def test_empty_method_raises_validation_error(self):
        with pytest.raises(ValidationError, match="method"):
            AgentConnectionInput(
                name="No Method",
                type="chatbot",
                connection=ConnectionConfig(method="", url="https://x.test"),
            )

    def test_whitespace_only_method_raises_validation_error(self):
        with pytest.raises(ValidationError, match="method"):
            AgentConnectionInput(
                name="Whitespace Method",
                type="chatbot",
                connection=ConnectionConfig(method="   ", url="https://x.test"),
            )


# ===========================================================================
# 8. Unsupported method (unknown method string)
# ===========================================================================

class TestUnsupportedMethod:
    def test_unknown_method_for_chatbot_raises(self):
        with pytest.raises(ValidationError, match="not supported"):
            AgentConnectionInput(
                name="SSE Chatbot",
                type="chatbot",
                connection=ConnectionConfig(method="sse", url="https://x.test"),
            )

    def test_unknown_method_for_voice_raises(self):
        with pytest.raises(ValidationError, match="not supported"):
            AgentConnectionInput(
                name="SIP Agent",
                type="voice",
                connection=ConnectionConfig(method="sip", url="sip://x.test"),
            )

    def test_completely_unknown_method_raises(self):
        with pytest.raises(ValidationError, match="not supported"):
            AgentConnectionInput(
                name="Unknown Method",
                type="chatbot",
                connection=ConnectionConfig(method="carrier_pigeon", url="https://x.test"),
            )


# ===========================================================================
# 9. Chatbot + voice-only method mismatch
# ===========================================================================

class TestChatbotVoiceMethodMismatch:
    def test_livekit_method_for_chatbot_raises(self):
        with pytest.raises(ValidationError, match="not supported for type='chatbot'"):
            AgentConnectionInput(
                name="Wrong Chatbot",
                type="chatbot",
                connection=ConnectionConfig(method="livekit", url="wss://x.test"),
            )

    def test_local_method_for_chatbot_raises(self):
        with pytest.raises(ValidationError, match="not supported for type='chatbot'"):
            AgentConnectionInput(
                name="Wrong Chatbot Local",
                type="chatbot",
                connection=ConnectionConfig(method="local"),
            )

    def test_fake_method_for_chatbot_raises(self):
        with pytest.raises(ValidationError, match="not supported for type='chatbot'"):
            AgentConnectionInput(
                name="Wrong Chatbot Fake",
                type="chatbot",
                connection=ConnectionConfig(method="fake"),
            )


# ===========================================================================
# 10. Voice + chatbot-only method mismatch
# ===========================================================================

class TestVoiceChatbotMethodMismatch:
    def test_rest_method_for_voice_raises(self):
        with pytest.raises(ValidationError, match="not supported for type='voice'"):
            AgentConnectionInput(
                name="Wrong Voice REST",
                type="voice",
                connection=ConnectionConfig(method="rest", url="https://x.test"),
            )

    def test_websocket_method_for_voice_raises(self):
        with pytest.raises(ValidationError, match="not supported for type='voice'"):
            AgentConnectionInput(
                name="Wrong Voice WS",
                type="voice",
                connection=ConnectionConfig(method="websocket", url="wss://x.test"),
            )

    def test_browser_method_for_voice_raises(self):
        with pytest.raises(ValidationError, match="not supported for type='voice'"):
            AgentConnectionInput(
                name="Wrong Voice Browser",
                type="voice",
                connection=ConnectionConfig(method="browser", url="https://x.test"),
            )


# ===========================================================================
# 11. Generic authentication
# ===========================================================================

class TestGenericAuthentication:
    FAKE_KEY = "FAKE_API_KEY_TEST_XYZ_123"
    FAKE_TOKEN = "FAKE_BEARER_TOKEN_TEST_ABC_456"

    def test_api_key_auth_accepted(self):
        inp = _chatbot_rest_input()
        inp = AgentConnectionInput(
            name="Auth REST",
            type="chatbot",
            connection=ConnectionConfig(
                method="rest",
                url="https://fake.example.test/chat",
                auth=AuthConfig(type="api_key", value=self.FAKE_KEY),
            ),
        )
        assert inp.connection.auth is not None
        assert inp.connection.auth.type == "api_key"

    def test_bearer_auth_accepted(self):
        inp = AgentConnectionInput(
            name="Bearer REST",
            type="chatbot",
            connection=ConnectionConfig(
                method="rest",
                url="https://fake.example.test/chat",
                auth=AuthConfig(type="bearer", value=self.FAKE_TOKEN),
            ),
        )
        assert inp.connection.auth.type == "bearer"

    def test_auth_stored_in_config_after_parsing(self):
        inp = AgentConnectionInput(
            name="Auth Check",
            type="chatbot",
            connection=ConnectionConfig(
                method="rest",
                url="https://fake.example.test/chat",
                auth=AuthConfig(type="api_key", value=self.FAKE_KEY),
            ),
        )
        conn = parse_connection_input(inp)
        assert "auth" in conn.config
        assert conn.config["auth"]["type"] == "api_key"
        # value is present in the config for the adapter to consume
        # but it must NOT appear in AgentConnection repr / str
        assert self.FAKE_KEY not in repr(conn)
        assert self.FAKE_KEY not in str(conn)

    def test_auth_repr_does_not_expose_secret(self):
        auth = AuthConfig(type="api_key", value=self.FAKE_KEY)
        r = repr(auth)
        assert self.FAKE_KEY not in r
        assert "redacted" in r.lower()

    def test_auth_str_does_not_expose_secret(self):
        auth = AuthConfig(type="api_key", value=self.FAKE_KEY)
        assert self.FAKE_KEY not in str(auth)

    def test_no_auth_is_fine(self):
        inp = _chatbot_rest_input()
        conn = parse_connection_input(inp)
        assert "auth" not in conn.config


# ===========================================================================
# 12. Options/config passthrough
# ===========================================================================

class TestOptionsPassthrough:
    def test_options_merged_into_adapter_config(self):
        inp = AgentConnectionInput(
            name="Chatbot With Options",
            type="chatbot",
            connection=ConnectionConfig(
                method="rest",
                url="https://fake.example.test/chat",
                options={
                    "response_mapping": {"reply_field": "data.text"},
                    "timeout": 10,
                },
            ),
        )
        conn = parse_connection_input(inp)
        assert conn.config.get("response_mapping") == {"reply_field": "data.text"}
        assert conn.config.get("timeout") == 10

    def test_options_override_url_key_if_provided(self):
        """
        If options contains the url key explicitly, the options value wins
        (merge order: url first, then options).
        """
        inp = AgentConnectionInput(
            name="Override URL",
            type="chatbot",
            connection=ConnectionConfig(
                method="rest",
                url="https://original.example.test",
                options={"base_url": "https://override.example.test"},
            ),
        )
        conn = parse_connection_input(inp)
        assert conn.config["base_url"] == "https://override.example.test"

    def test_livekit_options_merged(self):
        inp = _voice_livekit_input()
        conn = parse_connection_input(inp)
        assert conn.config.get("agent_name") == "test-agent"

    def test_empty_options_does_not_pollute_config(self):
        inp = AgentConnectionInput(
            name="No Options",
            type="chatbot",
            connection=ConnectionConfig(
                method="rest",
                url="https://fake.example.test/chat",
                options={},
            ),
        )
        conn = parse_connection_input(inp)
        # The config should have the url keys but nothing extra
        assert "agent_name" not in conn.config


# ===========================================================================
# 13. Secrets not exposed
# ===========================================================================

class TestSecretsNotExposed:
    FAKE_SECRET = "SUPER_FAKE_SECRET_DO_NOT_EXPOSE_12345"

    def test_secret_not_in_agent_connection_repr(self):
        inp = AgentConnectionInput(
            name="Secret Test",
            type="chatbot",
            connection=ConnectionConfig(
                method="rest",
                url="https://fake.example.test",
                auth=AuthConfig(type="api_key", value=self.FAKE_SECRET),
            ),
        )
        conn = parse_connection_input(inp)
        assert self.FAKE_SECRET not in repr(conn)
        assert self.FAKE_SECRET not in str(conn)

    def test_secret_not_in_connection_test_result(self):
        """Secrets in adapter config must not leak into ConnectionTestResult."""
        mock_adapter = MagicMock()
        mock_adapter.connect.return_value = None

        registry = AdapterRegistry()
        registry.register("chatbot", "rest", lambda cfg: mock_adapter)
        manager = ConnectionManager(registry=registry)

        inp = AgentConnectionInput(
            name="Secret Result Test",
            type="chatbot",
            connection=ConnectionConfig(
                method="rest",
                url="https://fake.example.test",
                auth=AuthConfig(type="api_key", value=self.FAKE_SECRET),
            ),
        )
        result = connect_and_test(inp, manager=manager)
        assert self.FAKE_SECRET not in result.message
        if result.details:
            assert self.FAKE_SECRET not in str(result.details)

    def test_auth_repr_never_exposes_value(self):
        auth = AuthConfig(type="bearer", value=self.FAKE_SECRET)
        assert self.FAKE_SECRET not in repr(auth)
        assert self.FAKE_SECRET not in str(auth)

    def test_validation_error_message_does_not_expose_secret(self):
        """Even validation errors must not echo credential values back."""
        try:
            AgentConnectionInput(
                name="",          # triggers validation error
                type="chatbot",
                connection=ConnectionConfig(
                    method="rest",
                    url="https://fake.example.test",
                    auth=AuthConfig(type="api_key", value=self.FAKE_SECRET),
                ),
            )
        except ValidationError as exc:
            assert self.FAKE_SECRET not in str(exc)


# ===========================================================================
# 14. Input successfully converted to AgentConnection
# ===========================================================================

class TestInputConvertedToAgentConnection:
    def test_produces_agent_connection_instance(self):
        inp = _chatbot_rest_input()
        conn = parse_connection_input(inp)
        assert isinstance(conn, AgentConnection)

    def test_id_auto_generated_when_not_supplied(self):
        inp = _chatbot_rest_input()
        conn = parse_connection_input(inp)
        assert conn.id and len(conn.id) > 0

    def test_custom_id_is_used(self):
        inp = _chatbot_rest_input()
        conn = parse_connection_input(inp, connection_id="my-custom-id-001")
        assert conn.id == "my-custom-id-001"

    def test_type_is_agent_type_enum(self):
        inp = _chatbot_rest_input()
        conn = parse_connection_input(inp)
        assert conn.type == AgentType.chatbot

    def test_adapter_equals_method(self):
        inp = _chatbot_rest_input()
        conn = parse_connection_input(inp)
        assert conn.adapter == "rest"

    def test_enabled_is_true_by_default(self):
        inp = _chatbot_rest_input()
        conn = parse_connection_input(inp)
        assert conn.enabled is True

    def test_voice_livekit_produces_voice_connection(self):
        inp = _voice_livekit_input()
        conn = parse_connection_input(inp)
        assert conn.type == AgentType.voice
        assert conn.adapter == "livekit"

    def test_type_coerced_to_agent_type(self):
        """'chatbot' string becomes AgentType.chatbot after parsing."""
        inp = _chatbot_rest_input()
        conn = parse_connection_input(inp)
        assert conn.type == AgentType.chatbot
        assert conn.type.value == "chatbot"


# ===========================================================================
# 15. connect_and_test() calls ConnectionManager
# ===========================================================================

class TestConnectAndTestCallsManager:
    def test_connect_and_test_calls_test_connection(self):
        mock_manager = _mock_manager_connected()
        inp = _chatbot_rest_input()
        connect_and_test(inp, manager=mock_manager)
        mock_manager.test_connection.assert_called_once()

    def test_connect_and_test_passes_agent_connection_to_manager(self):
        mock_manager = _mock_manager_connected()
        inp = _chatbot_rest_input()
        connect_and_test(inp, manager=mock_manager)

        call_args = mock_manager.test_connection.call_args
        passed_conn = call_args[0][0]  # first positional arg
        assert isinstance(passed_conn, AgentConnection)
        assert passed_conn.type == AgentType.chatbot
        assert passed_conn.adapter == "rest"

    def test_connect_and_test_uses_custom_id(self):
        mock_manager = _mock_manager_connected()
        inp = _chatbot_rest_input()
        connect_and_test(inp, connection_id="stable-id-xyz", manager=mock_manager)

        call_args = mock_manager.test_connection.call_args
        passed_conn = call_args[0][0]
        assert passed_conn.id == "stable-id-xyz"

    def test_connect_and_test_uses_default_manager_when_none_given(self):
        """When no manager is supplied, the default registry-backed manager is used."""
        inp = _chatbot_rest_input()
        # We just verify it creates one and calls test_connection without error.
        with patch("app.connections.parser.ConnectionManager") as MockMgr:
            mock_instance = MagicMock()
            mock_instance.test_connection.return_value = ConnectionTestResult(
                success=True,
                status=ConnectionStatus.connected,
                agent_id="x",
                adapter="rest",
                message="ok",
            )
            MockMgr.return_value = mock_instance
            connect_and_test(inp)  # no manager= argument
            MockMgr.assert_called_once()
            mock_instance.test_connection.assert_called_once()


# ===========================================================================
# 16. ConnectionTestResult is returned
# ===========================================================================

class TestConnectionTestResultReturned:
    def test_returns_connection_test_result(self):
        mock_manager = _mock_manager_connected()
        inp = _chatbot_rest_input()
        result = connect_and_test(inp, manager=mock_manager)
        assert isinstance(result, ConnectionTestResult)

    def test_successful_result_has_success_true(self):
        mock_manager = _mock_manager_connected()
        inp = _chatbot_rest_input()
        result = connect_and_test(inp, manager=mock_manager)
        assert result.success is True
        assert result.status == ConnectionStatus.connected

    def test_failed_result_propagated(self):
        manager = MagicMock(spec=ConnectionManager)
        manager.test_connection.return_value = ConnectionTestResult(
            success=False,
            status=ConnectionStatus.failed,
            agent_id="x",
            adapter="rest",
            message="Connection refused.",
        )
        inp = _chatbot_rest_input()
        result = connect_and_test(inp, manager=manager)
        assert result.success is False
        assert result.status == ConnectionStatus.failed

    def test_result_adapter_matches_method(self):
        """
        The adapter field in ConnectionTestResult must reflect what was
        requested, not some internal name.
        """
        manager = MagicMock(spec=ConnectionManager)
        manager.test_connection.return_value = ConnectionTestResult(
            success=True,
            status=ConnectionStatus.connected,
            agent_id="x",
            adapter="websocket",
            message="ok",
        )
        inp = _chatbot_ws_input()
        result = connect_and_test(inp, manager=manager)
        assert result.adapter == "websocket"


# ===========================================================================
# 17. Existing adapters are not modified
# ===========================================================================

class TestExistingAdaptersUnchanged:
    def test_rest_chat_adapter_class_importable(self):
        from app.adapters.chat.rest import RestChatAdapter
        assert RestChatAdapter is not None

    def test_websocket_chat_adapter_class_importable(self):
        from app.adapters.chat.websocket import WebSocketChatAdapter
        assert WebSocketChatAdapter is not None

    def test_browser_chat_adapter_class_importable(self):
        from app.adapters.chat.browser import BrowserChatAdapter
        assert BrowserChatAdapter is not None

    def test_fake_chat_adapter_class_importable(self):
        from app.adapters.chat.fake import FakeChatAdapter
        assert FakeChatAdapter is not None

    def test_livekit_voice_adapter_class_importable(self):
        from app.adapters.voice.livekit import LiveKitVoiceAdapter
        assert LiveKitVoiceAdapter is not None

    def test_fake_voice_adapter_class_importable(self):
        from app.adapters.voice.fake import FakeVoiceAdapter
        assert FakeVoiceAdapter is not None

    def test_local_voice_adapter_class_importable(self):
        from app.adapters.voice.local import LocalVoiceAdapter
        assert LocalVoiceAdapter is not None

    def test_adapter_factory_still_works(self):
        """Phase 3 must not break the existing AdapterFactory used by the orchestrator."""
        from app.adapters.factory import AdapterFactory
        assert AdapterFactory is not None

    def test_orchestrator_importable(self):
        """Phase 3 must not touch the orchestrator."""
        from app.orchestrator import run_scenario
        assert run_scenario is not None
