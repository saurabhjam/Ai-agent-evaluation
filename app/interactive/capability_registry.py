"""
Adapter action capability registry.

Phase 1 keeps capabilities declarative. No adapter is required to implement
new methods yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.interactive.models import ActionType


@dataclass
class AdapterCapability:
    adapter_name: str
    supported_actions: set[ActionType] = field(default_factory=set)
    native_interactive_metadata: bool = False
    notes: str = ""

    def supports(self, action_type: ActionType) -> bool:
        return action_type in self.supported_actions


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, AdapterCapability] = {}

    def register(self, capability: AdapterCapability) -> None:
        self._capabilities[capability.adapter_name] = capability

    def get(self, adapter_name: str) -> AdapterCapability:
        return self._capabilities.get(
            adapter_name,
            AdapterCapability(
                adapter_name=adapter_name,
                supported_actions={ActionType.send_text},
                notes="Default text-only capability.",
            ),
        )

    def supports(self, adapter_name: str, action_type: ActionType) -> bool:
        return self.get(adapter_name).supports(action_type)


def default_capability_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for adapter_name in ["rest", "browser", "websocket", "fake"]:
        registry.register(
            AdapterCapability(
                adapter_name=adapter_name,
                supported_actions={
                    ActionType.send_text,
                    ActionType.click_option,
                    ActionType.click_button,
                },
                notes="Phase 1 logical support: option/button actions can fall back to text submission in later phases.",
            )
        )
    for adapter_name in ["livekit", "local"]:
        registry.register(
            AdapterCapability(
                adapter_name=adapter_name,
                supported_actions={ActionType.send_text, ActionType.wait, ActionType.dtmf},
                notes="Voice actions are declarative only until later phases.",
            )
        )
    return registry
