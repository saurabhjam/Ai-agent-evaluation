"""
Client-facing Connection Input Models — Phase 3 of the Universal Agent
Connection System.

These models represent what a CLIENT provides to onboard their agent into
the evaluation platform.

Design separation
-----------------
CLIENT-FACING (this file)       INTERNAL (app/models/connection.py)
─────────────────────────────   ────────────────────────────────────
AgentConnectionInput            AgentConnection
ConnectionConfig                (uses AgentConnection.config)
AuthConfig                      (embedded in config dict)

The client-facing input is intentionally SIMPLE:
    - name        → human label
    - type        → chatbot | voice
    - connection  → method + url + optional auth + optional options

The internal AgentConnection is richer and used throughout the framework.
A parser (app/connections/parser.py) translates between them.

Who fills in AgentConnectionInput?
───────────────────────────────────
A future UI form, an API endpoint, a YAML file, or a CLI call.
The client does NOT need to know about AgentConnection, AdapterRegistry,
or any internal framework concept.

Supported connection methods (currently implemented)
──────────────────────────────────────────────────────
  Chatbot : rest | websocket | browser
  Voice   : livekit | local | fake

Methods NOT yet supported (no real adapter):
  sip | phone | webrtc | sse | custom

Design rules
────────────
- No vendor-specific field names.
- No business-domain fields.
- Credentials live only inside AuthConfig.value and are NEVER logged.
- All fields are validated at the Pydantic level before any connection
  attempt is made.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Method vocabulary — only currently implemented adapters
# ---------------------------------------------------------------------------

class ChatbotMethod(str, Enum):
    """Transport methods available for chatbot agents today."""
    rest      = "rest"
    websocket = "websocket"
    browser   = "browser"


class VoiceMethod(str, Enum):
    """Transport methods available for voice agents today."""
    livekit = "livekit"
    local   = "local"
    fake    = "fake"


# ---------------------------------------------------------------------------
# Authentication — generic, credential-safe
# ---------------------------------------------------------------------------

class AuthConfig(BaseModel):
    """
    Generic authentication descriptor.

    The ``type`` field identifies the auth scheme (e.g. "api_key", "bearer",
    "basic", "oauth2").  The ``value`` field carries the actual secret.

    IMPORTANT: ``value`` is intentionally excluded from repr/str so that
    secrets do not appear in logs, tracebacks, or error messages.

    For production use, ``value`` should be loaded from an environment
    variable or a secrets manager at runtime.  Clients should pass an
    env-var reference (e.g. "env:MY_API_KEY") and let the adapter resolve
    it, rather than embedding the raw secret in input payloads.
    """
    type: str = Field(
        ...,
        description="Auth scheme identifier (e.g. 'api_key', 'bearer', 'basic', 'oauth2').",
    )
    value: str = Field(
        ...,
        description=(
            "The credential value.  For production use, pass an env-var reference "
            "such as 'env:MY_SECRET_KEY' so the raw secret is never logged."
        ),
    )

    def __repr__(self) -> str:  # noqa: D105
        return f"AuthConfig(type={self.type!r}, value=<redacted>)"

    def __str__(self) -> str:  # noqa: D105
        return self.__repr__()


# ---------------------------------------------------------------------------
# Browser Selectors — generic DOM selectors for browser automation
# ---------------------------------------------------------------------------

class BrowserSelectors(BaseModel):
    """
    Generic CSS selectors required for browser-based chatbot adapters.
    """
    input: str = Field(..., description="CSS selector for the chat input field")
    submit: Optional[str] = Field(None, description="CSS selector for the send/submit button (optional if submit is via Enter key)")
    response: str = Field(..., description="CSS selector for the bot response messages")
    launcher: Optional[str] = Field(None, description="CSS selector for the chat launcher button to open the chat window")


# ---------------------------------------------------------------------------
# Connection configuration — the per-method transport block
# ---------------------------------------------------------------------------

class ConnectionConfig(BaseModel):
    """
    Transport configuration block inside AgentConnectionInput.

    Fields
    ──────
    method  : One of the currently supported adapter names.
              For chatbot: rest | websocket | browser
              For voice  : livekit | local | fake
    url     : The primary endpoint URL.  Required for all methods
              that communicate over a network (rest, websocket, browser,
              livekit).  Optional only for local/fake adapters.
    auth    : Optional generic authentication descriptor.
    options : Arbitrary extra configuration passed through to the
              adapter as-is.  Use this for adapter-specific parameters
              (e.g. agent_name for livekit) without polluting the
              top-level schema with vendor-specific fields.
    """

    method: str = Field(
        ...,
        description="Connection adapter to use (e.g. 'rest', 'livekit').",
    )
    url: Optional[str] = Field(
        default=None,
        description="Primary endpoint URL (required for network-based methods).",
    )
    auth: Optional[AuthConfig] = Field(
        default=None,
        description="Optional generic authentication configuration.",
    )
    selectors: Optional[BrowserSelectors] = Field(
        default=None,
        description="Optional CSS selectors (required when method='browser').",
    )
    options: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Adapter-specific parameters passed through to the adapter config. "
            "Example: {'agent_name': 'my-agent'} for LiveKit."
        ),
    )

    @field_validator("method")
    @classmethod
    def method_must_be_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("connection.method must be a non-empty string.")
        return v.strip().lower()


# ---------------------------------------------------------------------------
# Top-level client-facing input model
# ---------------------------------------------------------------------------

#: All methods that have a real adapter today.
_SUPPORTED_CHATBOT_METHODS: frozenset[str] = frozenset(m.value for m in ChatbotMethod)
_SUPPORTED_VOICE_METHODS:   frozenset[str] = frozenset(m.value for m in VoiceMethod)
_NETWORK_METHODS: frozenset[str] = frozenset({"rest", "websocket", "browser", "livekit"})


class AgentConnectionInput(BaseModel):
    """
    Minimal client-facing descriptor for connecting a new agent.

    Clients provide this.  The framework converts it internally to an
    AgentConnection via ``parse_connection_input()``.

    Fields
    ──────
    name        : Human-readable label for the agent (appears in reports).
    type        : "chatbot" or "voice".
    connection  : Transport block — method, URL, optional auth and options.

    Example — chatbot REST::

        AgentConnectionInput(
            name="Acme Chatbot",
            type="chatbot",
            connection=ConnectionConfig(
                method="rest",
                url="https://api.example.com/chat",
            ),
        )

    Example — voice LiveKit::

        AgentConnectionInput(
            name="Acme Voice Agent",
            type="voice",
            connection=ConnectionConfig(
                method="livekit",
                url="wss://livekit.example.com",
                options={"agent_name": "assistant"},
            ),
        )

    Validation enforced
    ───────────────────
    1. name must be non-empty.
    2. type must be "chatbot" or "voice".
    3. connection.method must be non-empty.
    4. connection.method must be compatible with the selected type.
    5. URL must be present for all network-based methods.
    6. Unsupported methods produce a clear validation error.
    """

    name: str = Field(
        ...,
        description="Human-readable label for the agent (appears in reports).",
    )
    type: str = Field(
        ...,
        description="Channel modality: 'chatbot' or 'voice'.",
    )
    connection: ConnectionConfig = Field(
        ...,
        description="Transport configuration block.",
    )
    backend_validation: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional backend validation connection catalog owned by this agent connection.",
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("name")
    @classmethod
    def name_must_be_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name must be a non-empty string.")
        return v.strip()

    @field_validator("type")
    @classmethod
    def type_must_be_valid(cls, v: str) -> str:
        normalised = v.strip().lower()
        if normalised not in ("chatbot", "voice"):
            raise ValueError(
                f"type must be 'chatbot' or 'voice', got '{v}'. "
                "Do not add industry-specific types."
            )
        return normalised

    @model_validator(mode="after")
    def validate_method_compatibility(self) -> "AgentConnectionInput":
        """
        Cross-field validation:
        1. connection.method must be supported for the selected type.
        2. URL must be present for network-based methods.
        """
        method = self.connection.method  # already lower-stripped by ConnectionConfig validator
        agent_type = self.type           # already normalised by type validator

        if agent_type == "chatbot":
            if method not in _SUPPORTED_CHATBOT_METHODS:
                _suggest = sorted(_SUPPORTED_CHATBOT_METHODS)
                raise ValueError(
                    f"connection.method='{method}' is not supported for type='chatbot'. "
                    f"Currently supported chatbot methods: {_suggest}. "
                    "Voice-only methods (livekit, local, fake) cannot be used with chatbot."
                )
        elif agent_type == "voice":
            if method not in _SUPPORTED_VOICE_METHODS:
                _suggest = sorted(_SUPPORTED_VOICE_METHODS)
                raise ValueError(
                    f"connection.method='{method}' is not supported for type='voice'. "
                    f"Currently supported voice methods: {_suggest}. "
                    "Chatbot-only methods (rest, websocket, browser) cannot be used with voice."
                )

        # URL required for all network-based methods
        if method in _NETWORK_METHODS and not self.connection.url:
            raise ValueError(
                f"connection.url is required when method='{method}'."
            )

        return self
