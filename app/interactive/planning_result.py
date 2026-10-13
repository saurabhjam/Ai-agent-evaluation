"""
Result wrapper for decision planning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.interactive.interaction_plan import InteractionPlan


@dataclass
class PlanningResult:
    success: bool
    plan: InteractionPlan | None = None
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
