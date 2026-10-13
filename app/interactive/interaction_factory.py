"""
Factory for creating universal chatbot interactions from scenario-like data.
"""

from __future__ import annotations

from typing import Any

from app.interactive.interaction_models import Interaction
from app.interactive.interaction_registry import InteractionRegistry, default_interaction_registry
from app.interactive.interaction_types import InteractionType


class InteractionFactory:
    def __init__(self, registry: InteractionRegistry | None = None) -> None:
        self.registry = registry or default_interaction_registry()

    def create(self, payload: Interaction | dict[str, Any]) -> Interaction:
        if isinstance(payload, Interaction):
            interaction = payload
        elif isinstance(payload, dict):
            interaction_kwargs = dict(
                type=InteractionType(payload["type"]),
                label=payload.get("label") or payload.get("name") or payload["type"],
                selector=payload.get("selector"),
                value=payload.get("value"),
                metadata=payload.get("metadata") or {},
                required=bool(payload.get("required", False)),
                timeout=payload.get("timeout"),
                provider_metadata=payload.get("provider_metadata") or {},
            )
            interaction_id = payload.get("id") or payload.get("interaction_id")
            if interaction_id:
                interaction_kwargs["id"] = interaction_id
            interaction = Interaction(**interaction_kwargs)
        else:
            raise TypeError("InteractionFactory.create() requires an Interaction or dict payload.")

        self.registry.get(interaction.type)
        return interaction
