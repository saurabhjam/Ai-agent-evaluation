"""
Universal form models for chatbot UI flows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.interactive.field_models import Field, FieldValidationRule
from app.interactive.form_state import FormSubmissionState


@dataclass
class UniversalForm:
    title: str
    fields: list[Field] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid4()))
    description: str | None = None
    validation_rules: list[FieldValidationRule] = field(default_factory=list)
    current_field: str | None = None
    completed_fields: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    submission_state: FormSubmissionState = FormSubmissionState.not_ready

    def __post_init__(self) -> None:
        self.id = self.id.strip() if self.id else ""
        if not self.id:
            raise ValueError("UniversalForm.id is required.")
        self.title = self.title.strip() if self.title else ""
        if not self.title:
            raise ValueError("UniversalForm.title is required.")
        self.description = self.description.strip() if self.description else None
        self.fields = [field if isinstance(field, Field) else Field(**field) for field in self.fields]
        self.validation_rules = [
            rule if isinstance(rule, FieldValidationRule) else FieldValidationRule(**rule)
            for rule in self.validation_rules
        ]
        if not isinstance(self.submission_state, FormSubmissionState):
            self.submission_state = FormSubmissionState(self.submission_state)
        self.refresh_state()

    @property
    def required_fields(self) -> list[Field]:
        return [field for field in self.fields if field.required]

    @property
    def optional_fields(self) -> list[Field]:
        return [field for field in self.fields if not field.required]

    @property
    def pending_fields(self) -> list[Field]:
        return [field for field in self.fields if field.id not in self.completed_fields]

    @property
    def is_ready_to_submit(self) -> bool:
        return all(field.id in self.completed_fields for field in self.required_fields)

    def refresh_state(self) -> None:
        self.completed_fields = [field.id for field in self.fields if field.is_completed]
        pending = self.pending_fields
        self.current_field = pending[0].id if pending else None
        if self.submission_state in {FormSubmissionState.submitted, FormSubmissionState.submitting, FormSubmissionState.failed}:
            return
        self.submission_state = FormSubmissionState.ready if self.is_ready_to_submit else FormSubmissionState.not_ready
