"""
Universal form engine for chatbot component understanding.

This module groups detected components into logical forms and tracks form
readiness. It does not perform DOM interaction, browser automation, uploads,
or real submission.
"""

from __future__ import annotations

import re
from typing import Any

from app.interactive.component_models import Component
from app.interactive.component_types import ComponentType
from app.interactive.field_models import Field
from app.interactive.field_types import FieldType
from app.interactive.form_context import FormContext
from app.interactive.form_models import UniversalForm
from app.interactive.form_result import FormResult


class DefaultFormEngine:
    name = "default"

    def understand(self, context: FormContext) -> FormResult:
        try:
            fields = [self._field_from_component(component, context.variables) for component in context.components]
            fields = [field for field in fields if field is not None]
            if not fields:
                return FormResult(
                    success=True,
                    forms=[],
                    metadata={"engine": self.name, "component_count": len(context.components)},
                )

            form = UniversalForm(
                title=str(context.metadata.get("title") or context.metadata.get("form_title") or "Detected Chatbot Form"),
                description=context.metadata.get("description"),
                fields=fields,
                metadata={
                    "engine": self.name,
                    "component_count": len(context.components),
                    "field_count": len(fields),
                },
            )
            return FormResult(success=True, forms=[form], metadata={"engine": self.name})
        except Exception as exc:
            return FormResult(success=False, error=f"{type(exc).__name__}: {exc}", metadata={"engine": self.name})

    def _field_from_component(self, component: Component, variables: dict[str, Any]) -> Field | None:
        field_type = self._field_type(component)
        if field_type is None:
            return None
        return Field(
            id=component.id,
            type=field_type,
            label=component.label,
            placeholder=component.text,
            required=component.required,
            default_value=component.value,
            current_value=self._variable_value(component, variables),
            options=component.options,
            provider_metadata=component.provider_metadata,
        )

    def _field_type(self, component: Component) -> FieldType | None:
        mapping = {
            ComponentType.text: None,
            ComponentType.button: None,
            ComponentType.quick_reply: None,
            ComponentType.dropdown: FieldType.dropdown,
            ComponentType.checkbox: FieldType.checkbox,
            ComponentType.radio_button: FieldType.radio,
            ComponentType.date_picker: FieldType.date,
            ComponentType.time_picker: FieldType.time,
            ComponentType.email_input: FieldType.email,
            ComponentType.phone_input: FieldType.phone,
            ComponentType.number_input: FieldType.number,
            ComponentType.otp_input: FieldType.otp,
            ComponentType.search_box: FieldType.search,
            ComponentType.text_area: FieldType.textarea,
            ComponentType.upload: FieldType.upload_file,
            ComponentType.link: FieldType.url,
            ComponentType.unknown: FieldType.custom,
        }
        return mapping.get(component.type)

    def _variable_value(self, component: Component, variables: dict[str, Any]) -> Any:
        candidates = {
            self._normalize_key(component.id),
            self._normalize_key(component.label),
            self._normalize_key(component.text or ""),
        }
        for key, value in variables.items():
            if self._normalize_key(str(key)) in candidates:
                return value
        return component.value

    def _normalize_key(self, value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
