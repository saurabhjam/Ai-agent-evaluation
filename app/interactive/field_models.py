"""
Provider-neutral field models for enterprise chatbot forms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.interactive.component_models import ComponentOption
from app.interactive.field_types import FieldType
from app.interactive.form_state import FieldValidationType


@dataclass
class FieldValidationRule:
    type: FieldValidationType
    value: Any = None
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.type, FieldValidationType):
            self.type = FieldValidationType(self.type)


@dataclass
class Field:
    type: FieldType
    label: str
    id: str = field(default_factory=lambda: str(uuid4()))
    placeholder: str | None = None
    required: bool = False
    default_value: Any = None
    current_value: Any = None
    options: list[ComponentOption] = field(default_factory=list)
    validation_rules: list[FieldValidationRule] = field(default_factory=list)
    provider_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.type, FieldType):
            self.type = FieldType(self.type)
        self.id = self.id.strip() if self.id else ""
        if not self.id:
            raise ValueError("Field.id is required.")
        self.label = self.label.strip() if self.label else ""
        if not self.label:
            raise ValueError("Field.label is required.")
        self.placeholder = self.placeholder.strip() if self.placeholder else None
        self.options = [
            option if isinstance(option, ComponentOption) else ComponentOption(**option)
            for option in self.options
        ]
        self.validation_rules = [
            rule if isinstance(rule, FieldValidationRule) else FieldValidationRule(**rule)
            for rule in self.validation_rules
        ]
        if self.required and not any(rule.type == FieldValidationType.required for rule in self.validation_rules):
            self.validation_rules.append(FieldValidationRule(type=FieldValidationType.required))

    @property
    def is_completed(self) -> bool:
        value = self.current_value if self.current_value is not None else self.default_value
        if isinstance(value, str):
            return bool(value.strip())
        return value is not None
