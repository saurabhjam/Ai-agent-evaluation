"""Variable extraction contracts for backend validation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseVariableExtractor(ABC):
    @abstractmethod
    def extract(
        self,
        transcript: list[Any],
        evaluation_context: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract variables from completed evaluation data."""
