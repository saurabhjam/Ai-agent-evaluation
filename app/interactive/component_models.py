"""
Provider-neutral models for detected chatbot UI components.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.interactive.component_types import ComponentType


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


@dataclass
class ComponentOption:
    label: str
    value: Any = None
    selector: str | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.label = self.label.strip() if self.label else ""
        if not self.label:
            raise ValueError("ComponentOption.label is required.")
        self.selector = _strip_optional(self.selector)

    def option_value(self) -> Any:
        return self.value if self.value is not None else self.label


@dataclass
class Component:
    type: ComponentType
    label: str
    id: str = field(default_factory=lambda: str(uuid4()))
    selector: str | None = None
    text: str | None = None
    value: Any = None
    required: bool = False
    enabled: bool = True
    visible: bool = True
    options: list[ComponentOption] = field(default_factory=list)
    provider_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.type, ComponentType):
            self.type = ComponentType(self.type)

        self.id = self.id.strip() if self.id else ""
        if not self.id:
            raise ValueError("Component.id is required.")

        self.label = self.label.strip() if self.label else ""
        if not self.label:
            raise ValueError("Component.label is required.")

        self.selector = _strip_optional(self.selector)
        self.text = _strip_optional(self.text)
        self.options = [
            option if isinstance(option, ComponentOption) else ComponentOption(**option)
            for option in self.options
        ]

    @property
    def has_options(self) -> bool:
        return bool(self.options)
