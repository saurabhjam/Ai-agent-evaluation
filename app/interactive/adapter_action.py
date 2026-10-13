"""
Optional adapter action contract helpers.

Adapters may implement get_capabilities() and execute_action(action), but the
User Action Engine must keep working when those methods are absent.
"""

from __future__ import annotations

from typing import Any

from app.interactive.adapter_capabilities import (
    AdapterCapabilities,
    browser_placeholder_capabilities,
    default_capabilities,
    rest_adapter_capabilities,
    voice_placeholder_capabilities,
)
from app.interactive.models import ActionType, UserAction


class AdapterCapabilityResolver:
    def capabilities_for(self, adapter: Any, *, adapter_name: str = "") -> AdapterCapabilities:
        if hasattr(adapter, "get_capabilities"):
            capabilities = adapter.get_capabilities()
            if isinstance(capabilities, AdapterCapabilities):
                return capabilities

        normalized_name = (adapter_name or adapter.__class__.__name__).lower()
        if normalized_name in {"rest", "fake", "websocket"} or "rest" in normalized_name:
            return rest_adapter_capabilities()
        if normalized_name == "browser" or "browser" in normalized_name:
            return browser_placeholder_capabilities()
        if normalized_name in {"livekit", "local"} or "voice" in normalized_name:
            return voice_placeholder_capabilities()
        return default_capabilities()

    def supports_native_action(
        self,
        adapter: Any,
        action_type: ActionType,
        *,
        adapter_name: str = "",
    ) -> bool:
        if action_type == ActionType.send_text:
            return False
        if not hasattr(adapter, "execute_action"):
            return False
        return self.capabilities_for(adapter, adapter_name=adapter_name).supports_action(action_type)

    def execute_native(self, adapter: Any, action: UserAction) -> None:
        adapter.execute_action(action)
