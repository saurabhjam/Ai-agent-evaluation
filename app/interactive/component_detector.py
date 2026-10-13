"""
Universal chatbot UI component detector.

The detector coordinates parser selection and returns a normalized result. It
does not execute interactions and contains no browser automation logic.
"""

from __future__ import annotations

from typing import Any

from app.interactive.component_parser import ComponentParser, ExplicitComponentParser
from app.interactive.component_registry import ComponentRegistry, default_component_registry
from app.interactive.component_result import ComponentResult


class ComponentDetector:
    def __init__(
        self,
        *,
        registry: ComponentRegistry | None = None,
        parsers: list[ComponentParser] | None = None,
    ) -> None:
        self.registry = registry or default_component_registry()
        self.parsers = parsers or [ExplicitComponentParser()]

    def detect(self, payload: Any, *, provider: str | None = None, metadata: dict[str, Any] | None = None) -> ComponentResult:
        try:
            parser = self._select_parser(payload, provider=provider)
            if parser is None:
                return ComponentResult(
                    success=False,
                    provider=provider,
                    raw_payload=payload,
                    metadata=metadata or {},
                    error="No component parser could handle the provider payload.",
                )

            components = parser.parse(payload, provider=provider)
            for component in components:
                self.registry.get(component.type)

            return ComponentResult(
                success=True,
                components=components,
                provider=provider or getattr(parser, "provider", None),
                raw_payload=payload,
                metadata=metadata or {},
            )
        except Exception as exc:
            return ComponentResult(
                success=False,
                provider=provider,
                raw_payload=payload,
                metadata=metadata or {},
                error=f"{type(exc).__name__}: {exc}",
            )

    def _select_parser(self, payload: Any, *, provider: str | None) -> ComponentParser | None:
        for parser in self.parsers:
            if parser.can_parse(payload, provider=provider):
                return parser
        return None
