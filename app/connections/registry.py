"""
Adapter Registry — Phase 2 of the Universal Agent Connection System.

Maps adapter names (free-form strings from AgentConnection.adapter) to
factory callables that produce the concrete adapter instances.

Design rules
------------
- Open/Closed: new adapters are registered here; AgentConnection is never
  modified to accommodate them.
- No vendor business logic: the registry knows ONLY how to instantiate
  adapters, not what those adapters do or which industry they serve.
- The registry owns only adapters that ACTUALLY exist in the codebase.
  Stubs / placeholders are NOT registered.
- The existing AdapterFactory (app/adapters/factory.py) is NOT replaced.
  It continues to serve the orchestrator unchanged.  The registry is an
  additive layer used exclusively by ConnectionManager.

Registered adapters (chatbot)
------------------------------
  rest       -> RestChatAdapter       (app/adapters/chat/rest.py)
  websocket  -> WebSocketChatAdapter  (app/adapters/chat/websocket.py)
  browser    -> BrowserChatAdapter    (app/adapters/chat/browser.py)
  fake       -> FakeChatAdapter       (app/adapters/chat/fake.py)

Registered adapters (voice)
-----------------------------
  livekit    -> LiveKitVoiceAdapter   (app/adapters/voice/livekit.py)
  fake       -> FakeVoiceAdapter      (app/adapters/voice/fake.py)
  local      -> LocalVoiceAdapter     (app/adapters/voice/local.py)

Adapters NOT yet registered (not implemented):
  sse, sip, phone, webrtc, custom  — will be registered when implemented.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.models.connection import AgentConnection, AgentType

logger = logging.getLogger(__name__)

# Type alias: a factory takes a config dict and returns an adapter instance.
AdapterFactory = Callable[..., Any]


class AdapterRegistrationError(Exception):
    """Raised when a registration attempt is invalid."""


class UnknownAdapterError(KeyError):
    """Raised when no adapter is registered for the requested name+type."""


# ---------------------------------------------------------------------------
# Registry class
# ---------------------------------------------------------------------------

class AdapterRegistry:
    """
    Maps (agent_type, adapter_name) → factory callable.

    The factory callable receives the AgentConnection.config dict and must
    return a ready-to-use adapter instance (ChatAdapter or VoiceAdapter).

    Usage
    -----
    >>> registry = AdapterRegistry()
    >>> registry.register("chatbot", "rest", lambda cfg: RestChatAdapter(cfg))
    >>> adapter = registry.create(connection)

    The default (singleton) registry is pre-populated with all adapters that
    actually exist in the project.  Use ``AdapterRegistry.default()`` to
    obtain it.
    """

    def __init__(self) -> None:
        # _store: {agent_type_value: {adapter_name: factory}}
        self._store: dict[str, dict[str, AdapterFactory]] = {
            AgentType.chatbot.value: {},
            AgentType.voice.value: {},
        }

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        agent_type: str,
        adapter_name: str,
        factory: AdapterFactory,
        *,
        overwrite: bool = False,
    ) -> None:
        """
        Register a factory callable for the given (agent_type, adapter_name).

        Parameters
        ----------
        agent_type   : "chatbot" or "voice"
        adapter_name : Free-form adapter identifier (e.g. "rest", "livekit").
        factory      : Callable[config_dict -> adapter_instance].
        overwrite    : Allow replacing an existing registration.
        """
        try:
            agent_type_val = AgentType(agent_type).value
        except ValueError:
            raise AdapterRegistrationError(
                f"Cannot register adapter for unknown agent type '{agent_type}'. "
                "Valid values: 'chatbot', 'voice'."
            )

        if not adapter_name or not adapter_name.strip():
            raise AdapterRegistrationError("adapter_name must be a non-empty string.")

        adapter_name = adapter_name.strip().lower()

        if adapter_name in self._store[agent_type_val] and not overwrite:
            raise AdapterRegistrationError(
                f"Adapter '{adapter_name}' for type '{agent_type_val}' is already "
                "registered.  Pass overwrite=True to replace it."
            )

        self._store[agent_type_val][adapter_name] = factory
        logger.debug("Registered adapter: type=%s name=%s", agent_type_val, adapter_name)

    # ------------------------------------------------------------------
    # Look-up
    # ------------------------------------------------------------------

    def get_factory(
        self,
        agent_type: str,
        adapter_name: str,
    ) -> AdapterFactory:
        """
        Return the factory for (agent_type, adapter_name).

        Raises UnknownAdapterError if not registered.
        """
        try:
            agent_type_val = AgentType(agent_type).value
        except ValueError:
            raise UnknownAdapterError(
                f"Unknown agent type '{agent_type}'. Valid values: 'chatbot', 'voice'."
            )

        adapter_name_norm = adapter_name.strip().lower()
        bucket = self._store.get(agent_type_val, {})

        if adapter_name_norm not in bucket:
            registered = sorted(bucket.keys())
            raise UnknownAdapterError(
                f"No adapter registered for type='{agent_type_val}' "
                f"name='{adapter_name_norm}'. "
                f"Registered for this type: {registered}"
            )

        return bucket[adapter_name_norm]

    def has(self, agent_type: str, adapter_name: str) -> bool:
        """Return True if a factory is registered for (agent_type, adapter_name)."""
        try:
            agent_type_val = AgentType(agent_type).value
        except ValueError:
            return False
        return adapter_name.strip().lower() in self._store.get(agent_type_val, {})

    def registered_adapters(self, agent_type: str) -> list[str]:
        """Return sorted list of registered adapter names for a given agent type."""
        try:
            agent_type_val = AgentType(agent_type).value
        except ValueError:
            return []
        return sorted(self._store.get(agent_type_val, {}).keys())

    # ------------------------------------------------------------------
    # Adapter creation
    # ------------------------------------------------------------------

    def create(
        self,
        connection: AgentConnection,
        evaluation_session: Any | None = None,
    ) -> Any:
        """
        Instantiate the correct adapter for the given AgentConnection.

        Raises UnknownAdapterError if adapter is not registered.
        """
        factory = self.get_factory(connection.type.value, connection.adapter)
        if evaluation_session is not None:
            import inspect

            signature = inspect.signature(factory)
            if (
                "evaluation_session" in signature.parameters
                or any(
                    param.kind == inspect.Parameter.VAR_KEYWORD
                    for param in signature.parameters.values()
                )
            ):
                return factory(
                    connection.config,
                    evaluation_session=evaluation_session,
                )
        return factory(connection.config)

    # ------------------------------------------------------------------
    # Default singleton
    # ------------------------------------------------------------------

    @classmethod
    def default(cls) -> "AdapterRegistry":
        """
        Return a registry pre-populated with all adapters that currently
        exist in the codebase.

        Only adapters with a real implementation are registered here.
        POC stubs or not-yet-implemented adapters are NOT registered.
        """
        registry = cls()
        _register_defaults(registry)
        return registry


# ---------------------------------------------------------------------------
# Default registrations
# ---------------------------------------------------------------------------

def _register_defaults(registry: AdapterRegistry) -> None:
    """
    Register all adapters that actually exist in the project.

    Imports are deferred (inside lambdas) so that missing optional
    dependencies (e.g. livekit) don't crash the import of this module.
    """

    # ---- chatbot -------------------------------------------------------
    registry.register(
        "chatbot", "rest",
        lambda cfg, evaluation_session=None: _import_and_create(
            "app.adapters.chat.rest",
            "RestChatAdapter",
            cfg,
            evaluation_session=evaluation_session,
        ),
    )
    registry.register(
        "chatbot", "websocket",
        lambda cfg, evaluation_session=None: _import_and_create("app.adapters.chat.websocket", "WebSocketChatAdapter", cfg),
    )
    registry.register(
        "chatbot", "browser",
        lambda cfg, evaluation_session=None: _import_and_create("app.adapters.chat.browser", "BrowserChatAdapter", cfg),
    )
    registry.register(
        "chatbot", "fake",
        lambda cfg, evaluation_session=None: _import_and_create("app.adapters.chat.fake", "FakeChatAdapter", cfg),
    )

    # ---- voice ---------------------------------------------------------
    registry.register(
        "voice", "livekit",
        lambda cfg, evaluation_session=None: _import_and_create("app.adapters.voice.livekit", "LiveKitVoiceAdapter", cfg),
    )
    registry.register(
        "voice", "fake",
        lambda cfg, evaluation_session=None: _import_and_create("app.adapters.voice.fake", "FakeVoiceAdapter", cfg),
    )
    registry.register(
        "voice", "local",
        lambda cfg, evaluation_session=None: _import_and_create("app.adapters.voice.local", "LocalVoiceAdapter", cfg),
    )


def _import_and_create(
    module_path: str,
    class_name: str,
    config: dict[str, Any],
    evaluation_session: Any | None = None,
) -> Any:
    """
    Lazily import module_path, then instantiate class_name(config).

    Deferred import keeps optional heavy dependencies (livekit SDK,
    faster-whisper, etc.) from being required at module load time.
    """
    import importlib
    import inspect
    module = importlib.import_module(module_path)
    adapter_cls = getattr(module, class_name)
    if evaluation_session is not None:
        signature = inspect.signature(adapter_cls)
        if "evaluation_session" in signature.parameters:
            return adapter_cls(config, evaluation_session=evaluation_session)
    return adapter_cls(config)
