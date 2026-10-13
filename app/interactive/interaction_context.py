"""
Execution context passed to interaction adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InteractionContext:
    adapter: Any
    scenario_id: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
