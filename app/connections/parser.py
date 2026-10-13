"""
Connection Input Parser — Phase 3 of the Universal Agent Connection System.

Translates the simple client-facing AgentConnectionInput into the internal
AgentConnection model used by ConnectionManager / AdapterRegistry.

The full one-call flow is:

    AgentConnectionInput          (client provides this)
            ↓
    parse_connection_input()      (this module)
            ↓
    AgentConnection               (internal model, Phase 1)
            ↓
    ConnectionManager             (Phase 2)
            ↓
    AdapterRegistry → adapter
            ↓
    ConnectionTestResult          (returned to caller)

Design rules
────────────
- Stateless: both functions are pure (no global state, no side effects
  beyond logging).
- No duplication: all connection/adapter logic remains in ConnectionManager
  and AdapterRegistry; the parser only translates the data model.
- Credential-safe: auth.value is moved into the adapter config dict under
  a generic key; it is never printed, logged, or included in result fields.
- No business logic: the parser knows nothing about refunds, bookings,
  banking, healthcare, e-commerce, or any client-specific domain.

Public API
──────────
    from app.connections.parser import parse_connection_input, connect_and_test

    connection = parse_connection_input(agent_input)   # AgentConnection
    result     = connect_and_test(agent_input)         # ConnectionTestResult
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from app.connections.browser_token import resolve_browser_token_strategy
from app.connections.input import AgentConnectionInput
from app.connections.manager import ConnectionManager
from app.connections.result import ConnectionTestResult
from app.models.connection import AgentConnection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_connection_input(
    agent_input: AgentConnectionInput,
    *,
    connection_id: Optional[str] = None,
) -> AgentConnection:
    """
    Convert a client-facing AgentConnectionInput into an internal AgentConnection.

    Parameters
    ──────────
    agent_input   : Validated client input (must already pass Pydantic validation).
    connection_id : Optional stable ID.  Auto-generated UUID if not provided.

    Returns
    ───────
    AgentConnection ready to be passed to ConnectionManager.

    Config normalisation
    ────────────────────
    The adapter config dict is assembled from three sources, in priority order:
    1. ``connection.url``    — stored as the canonical URL key for the adapter.
    2. ``connection.auth``   — stored as a generic ``auth`` dict {type, value}.
                               (Never logged; consumed by the adapter.)
    3. ``connection.options`` — merged in last so clients can override anything.

    URL key mapping
    ───────────────
    Different adapters use different config keys for the primary URL.
    The parser normalises them:

        rest / websocket / browser → "base_url"  (and "endpoint" = url as fallback)
        livekit                    → "server_url"
        local / fake               → "base_url"   (if url provided)
    """
    conn_id = (connection_id or str(uuid.uuid4())).strip()
    method  = agent_input.connection.method   # already lower-normalised
    url     = agent_input.connection.url

    # Build the adapter config dict
    config: dict[str, Any] = {}

    # 1. URL — map to the key the concrete adapter expects
    if url:
        url_key = _url_key_for_method(method)
        config[url_key] = url

        # REST adapter also accepts "endpoint" as a direct target when no
        # base_url + send/receive configuration is provided.
        if method == "rest" and "endpoint" not in config:
            config["endpoint"] = url

    # 2. Authentication — generic auth dict (never logged)
    if agent_input.connection.auth is not None:
        config["auth"] = {
            "type":  agent_input.connection.auth.type,
            "value": agent_input.connection.auth.value,  # kept in config, not in result
        }

    # 3. Selectors — generic DOM selectors for browser automation
    if hasattr(agent_input.connection, "selectors") and agent_input.connection.selectors is not None:
        config["selectors"] = agent_input.connection.selectors.model_dump(exclude_none=True)

    # 4. Extra options — merged last (client can override anything above)
    if agent_input.connection.options:
        config.update(agent_input.connection.options)
        
        # UI stores browser login fields in options, but RestChatAdapter expects them in auth
        if config.get("auth") and config["auth"].get("type") == "browser_token":
            for key in ["browser_login_url", "intercept_pattern", "token_path", "header_name", "header_format", "script", "trigger_script", "delete_cookies"]:
                if key in agent_input.connection.options:
                    # Rename browser_login_url to url for the adapter
                    target_key = "url" if key == "browser_login_url" else key
                    config["auth"][target_key] = agent_input.connection.options[key]


    agent_connection = AgentConnection(
        id=conn_id,
        name=agent_input.name,
        type=agent_input.type,      # "chatbot" or "voice"
        adapter=method,             # e.g. "rest", "livekit"
        config=config,
        backend_validation=agent_input.backend_validation,
        enabled=True,
    )

    logger.debug(
        "parse_connection_input: created AgentConnection "
        "(id=%s type=%s adapter=%s)",
        conn_id, agent_input.type, method,
    )

    return agent_connection


# ---------------------------------------------------------------------------
# One-call service
# ---------------------------------------------------------------------------

def connect_and_test(
    agent_input: AgentConnectionInput,
    *,
    connection_id: Optional[str] = None,
    manager: Optional[ConnectionManager] = None,
) -> ConnectionTestResult:
    """
    Validate input, parse it into an AgentConnection, and test connectivity.

    This is the single entry-point for a future UI or API endpoint.
    The caller does NOT need to know about AgentConnection, AdapterRegistry,
    or any concrete adapter class.

    Parameters
    ──────────
    agent_input   : Client-provided connection descriptor (already validated
                    by Pydantic on construction).
    connection_id : Optional stable connection ID to assign.
    manager       : Optional ConnectionManager instance.  Uses the default
                    (pre-populated with all real adapters) if not supplied.

    Returns
    ───────
    ConnectionTestResult  — normalised, credential-safe outcome.

    Example
    ───────
    ::
        from app.connections.input import AgentConnectionInput, ConnectionConfig
        from app.connections.parser import connect_and_test

        result = connect_and_test(
            AgentConnectionInput(
                name="Client Chatbot",
                type="chatbot",
                connection=ConnectionConfig(
                    method="rest",
                    url="https://client.example.com/chat",
                ),
            )
        )
        print(result.success, result.status)
    """
    _manager = manager if manager is not None else ConnectionManager()

    connection = parse_connection_input(agent_input, connection_id=connection_id)

    logger.info(
        "connect_and_test: starting connection test "
        "(name=%r type=%s method=%s)",
        agent_input.name,
        agent_input.type,
        agent_input.connection.method,
    )

    result = _manager.test_connection(connection)

    logger.info(
        "connect_and_test: result status=%s success=%s",
        result.status, result.success,
    )

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _url_key_for_method(method: str) -> str:
    """
    Return the config-dict key that the concrete adapter uses for its URL.

    This mapping must stay in sync with the actual adapter constructors.
    It is intentionally the ONLY place where adapter-specific knowledge
    leaks into the parser — and only at the level of a config-key name.
    """
    _METHOD_URL_KEYS: dict[str, str] = {
        "rest":      "base_url",
        "websocket": "base_url",
        "browser":   "base_url",
        "livekit":   "server_url",
        "local":     "base_url",
        "fake":      "base_url",
    }
    return _METHOD_URL_KEYS.get(method, "url")
