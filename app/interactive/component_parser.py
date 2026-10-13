"""
Provider-neutral component parser contracts.

Parsers convert provider-specific payloads into universal components. This
phase defines the architecture and a minimal explicit-payload parser for tests
and future adapters. It does not implement Botpress, DOM, Playwright, Selenium,
or any provider-specific logic.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.interactive.component_models import Component
from app.interactive.component_types import ComponentType


class ComponentParser(Protocol):
    provider: str

    def can_parse(self, payload: Any, *, provider: str | None = None) -> bool:
        """Return True when this parser can normalize the payload."""

    def parse(self, payload: Any, *, provider: str | None = None) -> list[Component]:
        """Return universal components extracted from the payload."""


class ExplicitComponentParser:
    """
    Parses payloads that already expose a generic ``components`` list.

    This is a provider-neutral bridge shape for adapters that can provide
    normalized metadata without coupling this layer to a vendor.
    """

    provider = "generic"

    def can_parse(self, payload: Any, *, provider: str | None = None) -> bool:
        return isinstance(payload, dict) and isinstance(payload.get("components"), list)

    def parse(self, payload: Any, *, provider: str | None = None) -> list[Component]:
        if not self.can_parse(payload, provider=provider):
            return []
        return [self._component_from_item(item) for item in payload.get("components", []) if isinstance(item, dict)]

    def _component_from_item(self, item: dict[str, Any]) -> Component:
        component_kwargs = dict(
            type=ComponentType(item.get("type", ComponentType.unknown.value)),
            label=item.get("label") or item.get("text") or item.get("type") or ComponentType.unknown.value,
            selector=item.get("selector"),
            text=item.get("text"),
            value=item.get("value"),
            required=bool(item.get("required", False)),
            enabled=bool(item.get("enabled", True)),
            visible=bool(item.get("visible", True)),
            options=item.get("options") or [],
            provider_metadata=item.get("provider_metadata") or {},
        )
        component_id = item.get("id") or item.get("component_id")
        if component_id:
            component_kwargs["id"] = component_id
        return Component(**component_kwargs)
