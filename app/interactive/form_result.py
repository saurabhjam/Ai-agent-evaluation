"""
Result model for universal form understanding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.interactive.form_models import UniversalForm


@dataclass
class FormResult:
    success: bool
    forms: list[UniversalForm] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def form_count(self) -> int:
        return len(self.forms)
