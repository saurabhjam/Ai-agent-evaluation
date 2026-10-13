"""
Universal Agent Connection Model — Phase 1.

Represents ONLY the transport/connection layer between the evaluation
framework and a client's AI agent.

This model intentionally does NOT encode:
- what the agent does (scenario / business logic)
- which industry or use-case the agent belongs to
- how the agent works internally
- which LLM / STT / TTS the client uses

Those concerns belong to separate layers.

Architecture separation:
    AGENT      — the client's AI system under evaluation
    CONNECTION — how our framework reaches that agent  <- this file
    SCENARIO   — what we instruct the agent to do
    EVALUATION — how we score the agent's behaviour

Supported channel types
-----------------------
    chatbot  — text-based interaction
    voice    — real-time audio interaction

Supported adapter types (open-ended — not exhaustive)
------------------------------------------------------
    Chatbot adapters : rest | websocket | browser | sse | custom | ...
    Voice adapters   : livekit | webrtc | websocket | sip | phone | custom | ...

New adapters can be added at the adapter layer without modifying this model.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AgentType(str, Enum):
    """
    High-level channel/modality of the agent under evaluation.

    Only two fundamental modalities are recognised.  Do NOT add
    industry-specific or use-case-specific values here.
    """
    chatbot = "chatbot"
    voice = "voice"


# ---------------------------------------------------------------------------
# Main model
# ---------------------------------------------------------------------------

class AgentConnection(BaseModel):
    """
    Provider-neutral descriptor for how the evaluation framework
    connects to a client's AI agent.

    Fields
    ------
    id       : Stable identifier for this connection definition.
    name     : Human-readable label (used in reports and logs).
    type     : Channel modality — ``chatbot`` or ``voice``.
    adapter  : Transport/adapter type (e.g. "rest", "livekit").
               This is intentionally a free-form string so that new
               adapters can be introduced without changing this model.
    config   : Adapter-specific connection configuration.
               Vendor/platform details and credentials belong here,
               not as top-level fields on this model.
    enabled  : Whether this connection is available for use in test runs.

    Security note
    -------------
    Credentials MUST be stored outside source control (e.g. via
    environment variables or a secrets manager) and referenced inside
    ``config`` at runtime.  This model does not log or expose field
    values in repr/str; sensitive values should be loaded from
    ``app.config.settings`` or equivalent.

    Examples
    --------
    >>> conn = AgentConnection(
    ...     id="agent_001",
    ...     name="Acme Chatbot",
    ...     type="chatbot",
    ...     adapter="rest",
    ...     config={"base_url": "https://api.example.com"},
    ... )

    >>> voice_conn = AgentConnection(
    ...     id="agent_002",
    ...     name="Acme Voice Agent",
    ...     type="voice",
    ...     adapter="livekit",
    ...     config={
    ...         "server_url": "wss://livekit.example.com",
    ...         "agent_name": "my-agent",
    ...     },
    ... )
    """

    id: str = Field(..., description="Unique identifier for this connection definition.")
    name: str = Field(..., description="Human-readable label used in reports and logs.")
    type: AgentType = Field(..., description="Channel modality: 'chatbot' or 'voice'.")
    adapter: str = Field(
        ...,
        description=(
            "Transport/adapter type (e.g. 'rest', 'websocket', 'livekit', 'sip'). "
            "Free-form string; new adapters do not require changes to this model."
        ),
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Adapter-specific connection parameters. "
            "All vendor/platform details and credential references belong here."
        ),
    )
    backend_validation: dict[str, Any] | None = Field(
        default=None,
        description="Optional backend validation connection catalog for post-evaluation checks.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this connection is available for use in test runs.",
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("id")
    @classmethod
    def id_must_be_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("AgentConnection.id must be a non-empty string.")
        return v.strip()

    @field_validator("name")
    @classmethod
    def name_must_be_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("AgentConnection.name must be a non-empty string.")
        return v.strip()

    @field_validator("adapter")
    @classmethod
    def adapter_must_be_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "AgentConnection.adapter must be a non-empty string "
                "(e.g. 'rest', 'websocket', 'livekit', 'sip', 'custom')."
            )
        return v.strip()

    # ------------------------------------------------------------------
    # Representation — keep config (and any embedded credentials) out
    # of logs, print statements, and error messages.
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"AgentConnection("
            f"id={self.id!r}, "
            f"name={self.name!r}, "
            f"type={self.type!r}, "
            f"adapter={self.adapter!r}, "
            f"enabled={self.enabled!r}"
            f")"
        )

    def __str__(self) -> str:
        return self.__repr__()
