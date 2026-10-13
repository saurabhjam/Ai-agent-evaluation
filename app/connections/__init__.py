"""
app.connections — Universal Agent Connection System (Phases 2 + 3).

Public API
──────────
    # Phase 2 — Connection infrastructure
    from app.connections import (
        ConnectionManager,
        AdapterRegistry,
        ConnectionTestResult,
        ConnectionStatus,
        UnknownAdapterError,
        AdapterRegistrationError,
    )

    # Phase 3 — Client-facing input layer
    from app.connections import (
        AgentConnectionInput,
        ConnectionConfig,
        AuthConfig,
        ChatbotMethod,
        VoiceMethod,
        parse_connection_input,
        connect_and_test,
    )
"""

# Phase 2
from app.connections.result import ConnectionStatus, ConnectionTestResult
from app.connections.registry import (
    AdapterRegistry,
    AdapterRegistrationError,
    UnknownAdapterError,
)
from app.connections.manager import ConnectionManager

# Phase 3
from app.connections.input import (
    AgentConnectionInput,
    ConnectionConfig,
    AuthConfig,
    ChatbotMethod,
    VoiceMethod,
)
from app.connections.parser import parse_connection_input, connect_and_test

__all__ = [
    # Phase 2
    "ConnectionManager",
    "AdapterRegistry",
    "AdapterRegistrationError",
    "UnknownAdapterError",
    "ConnectionTestResult",
    "ConnectionStatus",
    # Phase 3
    "AgentConnectionInput",
    "ConnectionConfig",
    "AuthConfig",
    "ChatbotMethod",
    "VoiceMethod",
    "parse_connection_input",
    "connect_and_test",
]
