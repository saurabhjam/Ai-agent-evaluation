"""
Context for the optional interactive chatbot runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeContext:
    scenario: Any = None
    adapter: Any = None
    provider_response: Any = None
    provider: str | None = None
    conversation_state: Any = None
    variables: dict[str, Any] = field(default_factory=dict)
    current_step: str | None = None
    previous_result: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.variables is None:
            self.variables = {}
        if self.metadata is None:
            self.metadata = {}
