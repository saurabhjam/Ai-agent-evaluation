"""
Connection Test Result — Phase 2 of the Universal Agent Connection System.

Represents the normalised outcome of a connection health-check.

Design rules
------------
- Provider-neutral: no vendor names in field names or status values.
- Credential-safe: secrets MUST NOT appear in any field (pass env-var
  names or omit entirely; never pass actual secret values).
- UI-ready: every field is serialisable and meaningful to a frontend.
- Pydantic v2 model so it integrates naturally with the rest of the stack.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------

class ConnectionStatus(str, Enum):
    """
    Normalised connection health-check outcome.

    Do NOT add industry-specific or vendor-specific values here.
    """
    connected           = "connected"           # adapter reached the agent successfully
    failed              = "failed"              # transport/network error
    unsupported         = "unsupported"         # adapter does not support the requested type
    disabled            = "disabled"            # connection.enabled is False
    configuration_error = "configuration_error" # missing / invalid adapter config
    unknown_adapter     = "unknown_adapter"     # adapter name not found in registry


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

class ConnectionTestResult(BaseModel):
    """
    Normalised result of ConnectionManager.test_connection().

    Intended for programmatic use and future UI display.

    Fields
    ------
    success    : True only when status == connected.
    status     : One of the ConnectionStatus values.
    agent_id   : The id from AgentConnection (useful for UI correlation).
    adapter    : The adapter name that was attempted.
    message    : Human-readable summary (safe for logging / display).
    details    : Optional structured diagnostic data.
                 MUST NOT contain credentials, API keys, or secrets.
    """

    success: bool = Field(..., description="True only when status is 'connected'.")
    status: ConnectionStatus = Field(..., description="Normalised outcome status.")
    agent_id: str = Field(..., description="AgentConnection.id for UI correlation.")
    adapter: str = Field(..., description="Adapter name that was attempted.")
    message: str = Field(..., description="Human-readable summary, safe for logging.")
    details: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional structured diagnostics. "
            "Must NOT contain API keys, secrets, or passwords."
        ),
    )

    # ------------------------------------------------------------------
    # Convenience factories
    # ------------------------------------------------------------------

    @classmethod
    def connected(
        cls,
        agent_id: str,
        adapter: str,
        message: str = "Connection successful.",
        details: Optional[dict[str, Any]] = None,
    ) -> "ConnectionTestResult":
        """Return a successful result."""
        return cls(
            success=True,
            status=ConnectionStatus.connected,
            agent_id=agent_id,
            adapter=adapter,
            message=message,
            details=details,
        )

    @classmethod
    def failed(
        cls,
        agent_id: str,
        adapter: str,
        message: str = "Connection failed.",
        details: Optional[dict[str, Any]] = None,
    ) -> "ConnectionTestResult":
        """Return a failure result."""
        return cls(
            success=False,
            status=ConnectionStatus.failed,
            agent_id=agent_id,
            adapter=adapter,
            message=message,
            details=details,
        )

    @classmethod
    def disabled(
        cls,
        agent_id: str,
        adapter: str,
        message: str = "Connection is disabled and cannot be tested.",
    ) -> "ConnectionTestResult":
        """Return a disabled result."""
        return cls(
            success=False,
            status=ConnectionStatus.disabled,
            agent_id=agent_id,
            adapter=adapter,
            message=message,
        )

    @classmethod
    def unsupported(
        cls,
        agent_id: str,
        adapter: str,
        message: str = "Adapter does not support the requested agent type.",
    ) -> "ConnectionTestResult":
        """Return an unsupported-type result."""
        return cls(
            success=False,
            status=ConnectionStatus.unsupported,
            agent_id=agent_id,
            adapter=adapter,
            message=message,
        )

    @classmethod
    def configuration_error(
        cls,
        agent_id: str,
        adapter: str,
        message: str = "Adapter configuration is invalid or incomplete.",
        details: Optional[dict[str, Any]] = None,
    ) -> "ConnectionTestResult":
        """Return a configuration-error result."""
        return cls(
            success=False,
            status=ConnectionStatus.configuration_error,
            agent_id=agent_id,
            adapter=adapter,
            message=message,
            details=details,
        )

    @classmethod
    def unknown_adapter(
        cls,
        agent_id: str,
        adapter: str,
        message: Optional[str] = None,
    ) -> "ConnectionTestResult":
        """Return an unknown-adapter result."""
        return cls(
            success=False,
            status=ConnectionStatus.unknown_adapter,
            agent_id=agent_id,
            adapter=adapter,
            message=message or f"No adapter registered for '{adapter}'.",
        )
