"""
Dispatcher for universal chatbot interactions.

Phase 1 defines the dispatch architecture only. Provider-specific methods may
be implemented by future adapters. Unsupported methods return structured
failure results instead of guessing browser behavior.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from app.interactive.interaction_context import InteractionContext
from app.interactive.interaction_models import Interaction
from app.interactive.interaction_registry import InteractionRegistry, default_interaction_registry
from app.interactive.interaction_result import InteractionResult
from app.interactive.interaction_types import InteractionType


class InteractionExecutor:
    def __init__(self, registry: InteractionRegistry | None = None) -> None:
        self.registry = registry or default_interaction_registry()

    def execute(self, interaction: Interaction, context: InteractionContext) -> InteractionResult:
        start = time.perf_counter()
        try:
            definition = self.registry.get(interaction.type)
            handler = self._resolve_handler(context.adapter, definition.handler_name)
            if handler is None:
                return InteractionResult(
                    success=False,
                    interaction_type=interaction.type,
                    latency=time.perf_counter() - start,
                    error=f"Adapter does not implement '{definition.handler_name}'.",
                    metadata={"interaction_id": interaction.id},
                )

            provider_response = handler(interaction, context)
            return InteractionResult(
                success=True,
                interaction_type=interaction.type,
                latency=time.perf_counter() - start,
                provider_response=provider_response,
                metadata={"interaction_id": interaction.id},
            )
        except Exception as exc:
            return InteractionResult(
                success=False,
                interaction_type=interaction.type,
                latency=time.perf_counter() - start,
                error=f"{type(exc).__name__}: {exc}",
                metadata={"interaction_id": interaction.id},
            )

    def _resolve_handler(self, adapter: Any, handler_name: str) -> Callable[[Interaction, InteractionContext], Any] | None:
        handler = getattr(adapter, handler_name, None)
        if callable(handler):
            return handler
        return None
