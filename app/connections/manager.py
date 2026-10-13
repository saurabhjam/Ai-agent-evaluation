"""
Connection Manager — Phase 2 of the Universal Agent Connection System.

Orchestrates the flow:

    AgentConnection
         ↓
    ConnectionManager
         ↓
    AdapterRegistry
         ↓
    Correct existing adapter
         ↓
    ConnectionTestResult

Design rules
------------
- Provider-neutral: the manager has ZERO knowledge of LiveKit, REST,
  WebSocket, SIP, Twilio, refunds, bookings, or any other domain concept.
- Credential-safe: secrets are never logged, never included in results.
- Non-destructive: the existing AdapterFactory and orchestrator are
  UNCHANGED.  The manager is a new, additive code path.
- Error-normalising: every failure surface is caught and converted into
  a ConnectionTestResult with an appropriate ConnectionStatus.

Public API
----------
    manager = ConnectionManager()
    result  = manager.test_connection(connection)     # ConnectionTestResult
    adapter = manager.create_adapter(connection)      # concrete adapter instance
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.connections.registry import AdapterRegistry, UnknownAdapterError
from app.connections.result import ConnectionStatus, ConnectionTestResult
from app.models.connection import AgentConnection, AgentType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases for capability flags we look for
# ---------------------------------------------------------------------------

_VOICE_ADAPTER_BASE_PATHS = ("app.adapters.voice.base",)


# ---------------------------------------------------------------------------
# Connection Manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """
    Provider-neutral gateway between an AgentConnection and a concrete adapter.

    The manager does NOT know:
    - What the agent does (refund, booking, …)
    - Which industry the client belongs to
    - Which LLM / STT / TTS the client uses
    - Any vendor-specific business rules

    It knows ONLY:
    - Is this connection enabled?
    - Is the adapter registered?
    - Does the adapter support the requested agent type?
    - Can we instantiate the adapter without error?

    Parameters
    ----------
    registry : AdapterRegistry
        Defaults to the shared default registry pre-populated with all
        adapters that exist in the codebase.  Pass a custom registry in
        tests or for isolated environments.
    """

    def __init__(self, registry: Optional[AdapterRegistry] = None) -> None:
        self._registry = registry if registry is not None else AdapterRegistry.default()

    # ------------------------------------------------------------------
    # Primary public API
    # ------------------------------------------------------------------

    def test_connection(self, connection: AgentConnection) -> ConnectionTestResult:
        """
        Attempt to reach the agent described by *connection* and return a
        normalised result.

        Flow
        ----
        1. Validate connection.enabled.
        2. Resolve the adapter from the registry.
        3. Validate that the adapter supports the requested agent type.
        4. Instantiate the adapter (catches config / import errors).
        5. Call adapter.connect() / adapter.start_session() as appropriate.
        6. Clean up, then return ConnectionTestResult.

        No credentials are ever included in the returned result or in logs.
        """
        agent_id = connection.id
        adapter_name = connection.adapter

        # -- Step 1: enabled check ---------------------------------------
        if not connection.enabled:
            logger.info(
                "connection_manager: test_connection skipped — connection disabled "
                "(id=%s adapter=%s)",
                agent_id, adapter_name,
            )
            return ConnectionTestResult.disabled(agent_id=agent_id, adapter=adapter_name)

        # -- Step 2: registry look-up ------------------------------------
        if not self._registry.has(connection.type.value, adapter_name):
            logger.warning(
                "connection_manager: no adapter registered for type=%s adapter=%s",
                connection.type.value, adapter_name,
            )
            registered = self._registry.registered_adapters(connection.type.value)
            return ConnectionTestResult.unknown_adapter(
                agent_id=agent_id,
                adapter=adapter_name,
                message=(
                    f"No adapter registered for type='{connection.type.value}' "
                    f"name='{adapter_name}'. "
                    f"Registered: {registered}"
                ),
            )

        # -- Step 3: type/adapter compatibility --------------------------
        #    We attempt instantiation and catch ValueError / TypeError that
        #    adapters raise when the config is wrong.  For the type-mismatch
        #    case we rely on the registry's type-keyed buckets: a "livekit"
        #    adapter will never be in the "chatbot" bucket, so if the user
        #    asks for type=chatbot adapter=livekit they get unknown_adapter.
        #    For the reverse (type=voice adapter=rest) we also get
        #    unknown_adapter because "rest" is not in the voice bucket.

        # -- Step 4: instantiate -----------------------------------------
        try:
            adapter = self._registry.create(connection)
        except (ValueError, TypeError, RuntimeError) as exc:
            # Strip any message that might contain credential fragments.
            safe_msg = _sanitise_error_message(str(exc))
            logger.warning(
                "connection_manager: adapter instantiation failed "
                "(id=%s adapter=%s): %s",
                agent_id, adapter_name, safe_msg,
            )
            return ConnectionTestResult.configuration_error(
                agent_id=agent_id,
                adapter=adapter_name,
                message=f"Adapter configuration error: {safe_msg}",
            )
        except ImportError as exc:
            safe_msg = _sanitise_error_message(str(exc))
            logger.warning(
                "connection_manager: adapter import failed "
                "(id=%s adapter=%s): %s",
                agent_id, adapter_name, safe_msg,
            )
            return ConnectionTestResult.configuration_error(
                agent_id=agent_id,
                adapter=adapter_name,
                message=f"Adapter import error (missing dependency?): {safe_msg}",
            )
        except Exception as exc:  # noqa: BLE001
            safe_msg = _sanitise_error_message(str(exc))
            logger.exception(
                "connection_manager: unexpected error during adapter instantiation "
                "(id=%s adapter=%s)",
                agent_id, adapter_name,
            )
            return ConnectionTestResult.failed(
                agent_id=agent_id,
                adapter=adapter_name,
                message=f"Unexpected error during adapter instantiation: {safe_msg}",
            )

        # -- Step 5: connect probe ---------------------------------------
        try:
            _probe_connect(adapter, connection)
        except (ConnectionError, OSError, TimeoutError) as exc:
            safe_msg = _sanitise_error_message(str(exc))
            logger.warning(
                "connection_manager: connection probe failed "
                "(id=%s adapter=%s): %s",
                agent_id, adapter_name, safe_msg,
            )
            return ConnectionTestResult.failed(
                agent_id=agent_id,
                adapter=adapter_name,
                message=f"Unable to connect to agent: {safe_msg}",
            )
        except NotImplementedError:
            # Adapter explicitly does not implement connect — that is OK for
            # adapters where connection happens per-session (e.g. LiveKit).
            pass
        except Exception as exc:  # noqa: BLE001
            safe_msg = _sanitise_error_message(str(exc))
            logger.warning(
                "connection_manager: connect probe raised unexpected exception "
                "(id=%s adapter=%s): %s",
                agent_id, adapter_name, safe_msg,
            )
            return ConnectionTestResult.failed(
                agent_id=agent_id,
                adapter=adapter_name,
                message=f"Connection probe failed: {safe_msg}",
            )

        # -- Step 6: success ---------------------------------------------
        logger.info(
            "connection_manager: test_connection succeeded (id=%s adapter=%s type=%s)",
            agent_id, adapter_name, connection.type.value,
        )
        return ConnectionTestResult.connected(
            agent_id=agent_id,
            adapter=adapter_name,
            message="Connection successful.",
            details={
                "agent_type": connection.type.value,
                "adapter": adapter_name,
            },
        )

    def create_adapter(
        self,
        connection: AgentConnection,
        evaluation_session: Any | None = None,
    ) -> Any:
        """
        Instantiate and return the concrete adapter for *connection*.

        Unlike test_connection() this method propagates exceptions so the
        caller can handle them directly (e.g. the orchestrator or a future
        async runner).

        Raises
        ------
        ValueError   if connection.enabled is False.
        UnknownAdapterError if the adapter is not registered.
        All other exceptions propagate from the adapter's __init__.
        """
        if not connection.enabled:
            raise ValueError(
                f"AgentConnection '{connection.id}' is disabled and cannot be used."
            )
        return self._registry.create(
            connection,
            evaluation_session=evaluation_session,
        )

    # ------------------------------------------------------------------
    # Introspection helpers (for future UI)
    # ------------------------------------------------------------------

    def registered_adapters(self, agent_type: str) -> list[str]:
        """Return the list of registered adapter names for *agent_type*."""
        return self._registry.registered_adapters(agent_type)

    def is_adapter_registered(self, agent_type: str, adapter_name: str) -> bool:
        """Return True if the given (agent_type, adapter_name) combination is registered."""
        return self._registry.has(agent_type, adapter_name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _probe_connect(adapter: Any, connection: AgentConnection) -> None:
    """
    Call the adapter's connect (chatbot) or the no-op connect (voice) method.

    VoiceAdapter.connect() is optional (documented as a no-op by default).
    ChatAdapter.connect() is abstract but may be a no-op in practice.

    We simply call whichever is present; NotImplementedError is allowed to
    propagate so the caller can decide whether that is acceptable.
    """
    if connection.type == AgentType.chatbot:
        # ChatAdapter defines connect() as abstract — call it.
        adapter.connect()
    else:
        # VoiceAdapter.connect() is optional (default no-op).
        # Call it but treat NotImplementedError as a benign case.
        try:
            adapter.connect()
        except NotImplementedError:
            pass


def _sanitise_error_message(msg: str) -> str:
    """
    Remove common patterns that could expose credentials in error messages.

    This is a best-effort defence-in-depth measure.  The primary defence is
    that adapters should never include credential values in their exception
    messages.
    """
    # Redact anything that looks like a token / key / secret / password value
    import re
    # Patterns: key=<value>, secret=<value>, token=<value>, password=<value>
    msg = re.sub(
        r'(?i)(key|secret|token|password|api_key|api_secret)\s*[=:]\s*\S+',
        r'\1=<redacted>',
        msg,
    )
    return msg
