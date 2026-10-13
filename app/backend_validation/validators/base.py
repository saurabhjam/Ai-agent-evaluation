"""Base backend validator contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.backend_validation.models import BackendValidationSummary


class BackendValidator(ABC):
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @abstractmethod
    def validate(self, *, transcript: list[Any], scenario: Any) -> BackendValidationSummary:
        """Validate completed evaluation data."""
