"""
Unit tests for app/models/connection.py — AgentConnection (Phase 1).

Requirements covered
--------------------
1.  Generic chatbot connection
2.  Generic voice connection
3.  Invalid agent type
4.  Empty ID
5.  Empty name
6.  Empty adapter
7.  Default config
8.  Default enabled value
9.  Arbitrary adapter configuration
10. Vendor/platform-specific configuration stored inside config
11. Credentials are not exposed in model representation/logging

All test values are synthetic — no real credentials or service URLs.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.connection import AgentConnection, AgentType


# ===========================================================================
# 1. Generic chatbot connection
# ===========================================================================

class TestChatbotConnection:
    def test_basic_chatbot_connection(self):
        conn = AgentConnection(
            id="test-chatbot-001",
            name="Test Chatbot",
            type="chatbot",
            adapter="rest",
            config={"base_url": "https://fake.example.test/chat"},
        )
        assert conn.id == "test-chatbot-001"
        assert conn.name == "Test Chatbot"
        assert conn.type == AgentType.chatbot
        assert conn.adapter == "rest"
        assert conn.config == {"base_url": "https://fake.example.test/chat"}
        assert conn.enabled is True

    def test_chatbot_websocket_adapter(self):
        conn = AgentConnection(
            id="test-chatbot-002",
            name="WebSocket Chatbot",
            type="chatbot",
            adapter="websocket",
            config={"url": "wss://fake.example.test/ws"},
        )
        assert conn.adapter == "websocket"
        assert conn.type == AgentType.chatbot

    def test_chatbot_browser_adapter(self):
        conn = AgentConnection(
            id="test-chatbot-003",
            name="Browser Chatbot",
            type="chatbot",
            adapter="browser",
            config={"launch_url": "https://fake.example.test"},
        )
        assert conn.adapter == "browser"

    def test_chatbot_sse_adapter(self):
        conn = AgentConnection(
            id="test-chatbot-004",
            name="SSE Chatbot",
            type="chatbot",
            adapter="sse",
        )
        assert conn.adapter == "sse"

    def test_chatbot_type_from_enum(self):
        conn = AgentConnection(
            id="test-chatbot-005",
            name="Enum Type Chatbot",
            type=AgentType.chatbot,
            adapter="rest",
        )
        assert conn.type == AgentType.chatbot
        assert conn.type == "chatbot"


# ===========================================================================
# 2. Generic voice connection
# ===========================================================================

class TestVoiceConnection:
    def test_basic_voice_connection(self):
        conn = AgentConnection(
            id="test-voice-001",
            name="Test Voice Agent",
            type="voice",
            adapter="livekit",
            config={
                "server_url": "wss://fake-livekit.example.test",
                "agent_name": "test-agent",
            },
        )
        assert conn.id == "test-voice-001"
        assert conn.name == "Test Voice Agent"
        assert conn.type == AgentType.voice
        assert conn.adapter == "livekit"
        assert conn.config["server_url"] == "wss://fake-livekit.example.test"
        assert conn.config["agent_name"] == "test-agent"

    def test_voice_webrtc_adapter(self):
        conn = AgentConnection(
            id="test-voice-002",
            name="WebRTC Voice Agent",
            type="voice",
            adapter="webrtc",
            config={"signaling_url": "wss://fake-signaling.example.test"},
        )
        assert conn.adapter == "webrtc"
        assert conn.type == AgentType.voice

    def test_voice_sip_adapter(self):
        conn = AgentConnection(
            id="test-voice-003",
            name="SIP Voice Agent",
            type="voice",
            adapter="sip",
            config={"sip_uri": "sip:test@fake.example.test"},
        )
        assert conn.adapter == "sip"

    def test_voice_phone_adapter(self):
        conn = AgentConnection(
            id="test-voice-004",
            name="Phone Agent",
            type="voice",
            adapter="phone",
            config={"phone_number": "+10000000000"},  # fake number
        )
        assert conn.adapter == "phone"

    def test_voice_type_from_enum(self):
        conn = AgentConnection(
            id="test-voice-005",
            name="Enum Voice Agent",
            type=AgentType.voice,
            adapter="livekit",
        )
        assert conn.type == AgentType.voice
        assert conn.type == "voice"


# ===========================================================================
# 3. Invalid agent type
# ===========================================================================

class TestInvalidAgentType:
    def test_rejects_unknown_type_string(self):
        with pytest.raises(ValidationError) as exc_info:
            AgentConnection(
                id="test-invalid-001",
                name="Bad Type Agent",
                type="phone_support",   # industry-specific — must be rejected
                adapter="rest",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("type",) for e in errors)

    def test_rejects_numeric_type(self):
        with pytest.raises(ValidationError):
            AgentConnection(
                id="test-invalid-002",
                name="Numeric Type",
                type=42,
                adapter="rest",
            )

    def test_rejects_none_type(self):
        with pytest.raises(ValidationError):
            AgentConnection(
                id="test-invalid-003",
                name="None Type",
                type=None,
                adapter="rest",
            )


# ===========================================================================
# 4. Empty ID
# ===========================================================================

class TestEmptyId:
    def test_rejects_empty_string_id(self):
        with pytest.raises(ValidationError) as exc_info:
            AgentConnection(
                id="",
                name="Test Agent",
                type="chatbot",
                adapter="rest",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("id",) for e in errors)

    def test_rejects_whitespace_only_id(self):
        with pytest.raises(ValidationError) as exc_info:
            AgentConnection(
                id="   ",
                name="Test Agent",
                type="chatbot",
                adapter="rest",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("id",) for e in errors)

    def test_strips_whitespace_from_valid_id(self):
        conn = AgentConnection(
            id="  agent-x  ",
            name="Test Agent",
            type="chatbot",
            adapter="rest",
        )
        assert conn.id == "agent-x"


# ===========================================================================
# 5. Empty name
# ===========================================================================

class TestEmptyName:
    def test_rejects_empty_string_name(self):
        with pytest.raises(ValidationError) as exc_info:
            AgentConnection(
                id="test-name-001",
                name="",
                type="chatbot",
                adapter="rest",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("name",) for e in errors)

    def test_rejects_whitespace_only_name(self):
        with pytest.raises(ValidationError) as exc_info:
            AgentConnection(
                id="test-name-002",
                name="   ",
                type="chatbot",
                adapter="rest",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("name",) for e in errors)

    def test_strips_whitespace_from_valid_name(self):
        conn = AgentConnection(
            id="test-name-003",
            name="  My Agent  ",
            type="chatbot",
            adapter="rest",
        )
        assert conn.name == "My Agent"


# ===========================================================================
# 6. Empty adapter
# ===========================================================================

class TestEmptyAdapter:
    def test_rejects_empty_string_adapter(self):
        with pytest.raises(ValidationError) as exc_info:
            AgentConnection(
                id="test-adapter-001",
                name="Test Agent",
                type="chatbot",
                adapter="",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("adapter",) for e in errors)

    def test_rejects_whitespace_only_adapter(self):
        with pytest.raises(ValidationError) as exc_info:
            AgentConnection(
                id="test-adapter-002",
                name="Test Agent",
                type="chatbot",
                adapter="   ",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("adapter",) for e in errors)

    def test_strips_whitespace_from_valid_adapter(self):
        conn = AgentConnection(
            id="test-adapter-003",
            name="Test Agent",
            type="chatbot",
            adapter="  rest  ",
        )
        assert conn.adapter == "rest"


# ===========================================================================
# 7. Default config
# ===========================================================================

class TestDefaultConfig:
    def test_config_defaults_to_empty_dict(self):
        conn = AgentConnection(
            id="test-config-001",
            name="Minimal Agent",
            type="chatbot",
            adapter="custom",
        )
        assert conn.config == {}
        assert isinstance(conn.config, dict)

    def test_config_instances_are_independent(self):
        """Each instance must have its own config dict (not a shared mutable default)."""
        conn_a = AgentConnection(
            id="test-config-002",
            name="Agent A",
            type="chatbot",
            adapter="custom",
        )
        conn_b = AgentConnection(
            id="test-config-003",
            name="Agent B",
            type="chatbot",
            adapter="custom",
        )
        conn_a.config["key"] = "value"
        assert "key" not in conn_b.config


# ===========================================================================
# 8. Default enabled value
# ===========================================================================

class TestDefaultEnabled:
    def test_enabled_defaults_to_true(self):
        conn = AgentConnection(
            id="test-enabled-001",
            name="Default Enabled Agent",
            type="chatbot",
            adapter="rest",
        )
        assert conn.enabled is True

    def test_enabled_can_be_set_to_false(self):
        conn = AgentConnection(
            id="test-enabled-002",
            name="Disabled Agent",
            type="chatbot",
            adapter="rest",
            enabled=False,
        )
        assert conn.enabled is False


# ===========================================================================
# 9. Arbitrary adapter configuration
# ===========================================================================

class TestArbitraryAdapterConfig:
    def test_accepts_arbitrary_string_adapter(self):
        """Adapter field is free-form — any non-empty string is valid."""
        conn = AgentConnection(
            id="test-arbitrary-001",
            name="Custom Transport Agent",
            type="chatbot",
            adapter="my-proprietary-protocol-v2",
            config={"endpoint": "https://fake.internal.test/v2/chat"},
        )
        assert conn.adapter == "my-proprietary-protocol-v2"

    def test_config_accepts_nested_dicts(self):
        conn = AgentConnection(
            id="test-arbitrary-002",
            name="Nested Config Agent",
            type="voice",
            adapter="webrtc",
            config={
                "ice_servers": [
                    {"urls": "stun:fake-stun.example.test:19302"},
                ],
                "transport": {"protocol": "udp"},
            },
        )
        assert isinstance(conn.config["ice_servers"], list)
        assert conn.config["transport"]["protocol"] == "udp"

    def test_config_accepts_various_value_types(self):
        conn = AgentConnection(
            id="test-arbitrary-003",
            name="Mixed Config Agent",
            type="chatbot",
            adapter="rest",
            config={
                "timeout_seconds": 30,
                "retries": 3,
                "verify_ssl": True,
                "headers": {"X-Custom": "test-value"},
                "tags": ["alpha", "beta"],
            },
        )
        assert conn.config["timeout_seconds"] == 30
        assert conn.config["verify_ssl"] is True
        assert "X-Custom" in conn.config["headers"]

    def test_serializes_to_dict_correctly(self):
        conn = AgentConnection(
            id="test-arbitrary-004",
            name="Serializable Agent",
            type="chatbot",
            adapter="rest",
            config={"base_url": "https://fake.example.test"},
        )
        d = conn.model_dump()
        assert d["id"] == "test-arbitrary-004"
        assert d["type"] == "chatbot"
        assert d["adapter"] == "rest"
        assert d["config"] == {"base_url": "https://fake.example.test"}
        assert d["enabled"] is True


# ===========================================================================
# 10. Vendor/platform-specific configuration stored inside config
# ===========================================================================

class TestVendorConfigInsideConfig:
    def test_livekit_config_inside_config(self):
        """LiveKit-specific parameters live in config, not as top-level fields."""
        conn = AgentConnection(
            id="test-vendor-001",
            name="LiveKit Agent",
            type="voice",
            adapter="livekit",
            config={
                "server_url": "wss://fake-livekit.example.test",
                "agent_name": "test-agent",
                # credential references come from env at runtime, not hardcoded here
                "api_key_env": "LIVEKIT_API_KEY",
                "api_secret_env": "LIVEKIT_API_SECRET",
            },
        )
        assert conn.config["server_url"] == "wss://fake-livekit.example.test"
        assert conn.config["api_key_env"] == "LIVEKIT_API_KEY"
        # No top-level livekit_url, livekit_api_key, etc.
        assert not hasattr(conn, "livekit_url")
        assert not hasattr(conn, "api_key")

    def test_rest_auth_config_inside_config(self):
        """REST auth config lives in config, not as top-level fields."""
        conn = AgentConnection(
            id="test-vendor-002",
            name="REST Chatbot with Auth",
            type="chatbot",
            adapter="rest",
            config={
                "base_url": "https://fake-api.example.test",
                "endpoint": "/v1/chat",
                "auth": {
                    "type": "bearer",
                    "token_env": "CHATBOT_API_TOKEN",   # env var reference, not real secret
                },
            },
        )
        assert conn.config["auth"]["type"] == "bearer"
        assert not hasattr(conn, "api_token")

    def test_phone_config_inside_config(self):
        """Telephony/SIP parameters live in config."""
        conn = AgentConnection(
            id="test-vendor-003",
            name="Phone Voice Agent",
            type="voice",
            adapter="phone",
            config={
                "phone_number": "+10000000000",   # synthetic test number
                "provider_env": "TELEPHONY_PROVIDER",
                "account_sid_env": "TELEPHONY_ACCOUNT_SID",
            },
        )
        assert conn.config["phone_number"] == "+10000000000"
        assert not hasattr(conn, "phone_number")
        assert not hasattr(conn, "twilio_number")

    def test_websocket_config_inside_config(self):
        """WebSocket-specific parameters live in config."""
        conn = AgentConnection(
            id="test-vendor-004",
            name="WebSocket Voice Agent",
            type="voice",
            adapter="websocket",
            config={
                "url": "wss://fake-voice.example.test/ws",
                "headers": {"Authorization": "Bearer {{FAKE_TOKEN_FROM_ENV}}"},
                "ping_interval": 20,
            },
        )
        assert conn.config["ping_interval"] == 20


# ===========================================================================
# 11. Credentials not exposed in repr / str / logging
# ===========================================================================

class TestCredentialSafety:
    def _make_conn_with_sensitive_config(self) -> AgentConnection:
        return AgentConnection(
            id="test-creds-001",
            name="Sensitive Config Agent",
            type="voice",
            adapter="livekit",
            config={
                "server_url": "wss://fake-livekit.example.test",
                "api_key": "FAKE_KEY_DO_NOT_LOG",
                "api_secret": "FAKE_SECRET_DO_NOT_LOG",
                "token": "FAKE_TOKEN_DO_NOT_LOG",
            },
        )

    def test_repr_does_not_contain_config_values(self):
        conn = self._make_conn_with_sensitive_config()
        representation = repr(conn)
        assert "FAKE_KEY_DO_NOT_LOG" not in representation
        assert "FAKE_SECRET_DO_NOT_LOG" not in representation
        assert "FAKE_TOKEN_DO_NOT_LOG" not in representation

    def test_str_does_not_contain_config_values(self):
        conn = self._make_conn_with_sensitive_config()
        representation = str(conn)
        assert "FAKE_KEY_DO_NOT_LOG" not in representation
        assert "FAKE_SECRET_DO_NOT_LOG" not in representation
        assert "FAKE_TOKEN_DO_NOT_LOG" not in representation

    def test_repr_contains_expected_identity_fields(self):
        conn = self._make_conn_with_sensitive_config()
        r = repr(conn)
        assert "test-creds-001" in r
        assert "Sensitive Config Agent" in r
        assert "livekit" in r

    def test_repr_does_not_contain_config_key_name(self):
        """The word 'config' itself should not appear in repr to avoid leaking key names."""
        conn = self._make_conn_with_sensitive_config()
        r = repr(conn)
        # config dict is entirely omitted from repr
        assert "config" not in r

    def test_model_dump_still_exposes_config_for_programmatic_use(self):
        """model_dump() is for programmatic use, not logging — it must still work."""
        conn = self._make_conn_with_sensitive_config()
        d = conn.model_dump()
        assert "api_key" in d["config"]
        assert d["config"]["api_key"] == "FAKE_KEY_DO_NOT_LOG"
