"""Registry for failure analysis generator functions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.models.failure_analysis import FailureAnalysis

FailureGenerator = Callable[[Any, dict[str, Any]], FailureAnalysis]


class FailureAnalysisRegistry:
    """Maps failure categories to generator functions."""

    def __init__(self) -> None:
        self._generators: dict[str, FailureGenerator] = {}

    def register_generator(self, category: str, generator: FailureGenerator) -> None:
        self._generators[_normalise_category(category)] = generator

    def get(self, category: str) -> FailureGenerator | None:
        return self._generators.get(_normalise_category(category))


def _normalise_category(category: str | None) -> str:
    return str(category or "unknown").strip().lower().replace("_", " ")
