"""
Validation for proposed user actions.

The validator is intentionally independent from runtime adapters. It validates
shape and declared capability support only.
"""

from __future__ import annotations

from app.interactive.capability_registry import CapabilityRegistry, default_capability_registry
from app.interactive.models import ActionType, ActionValidationResult, UserAction


class ActionValidator:
    def __init__(self, capability_registry: CapabilityRegistry | None = None) -> None:
        self.capabilities = capability_registry or default_capability_registry()

    def validate(self, action: UserAction, *, adapter_name: str) -> ActionValidationResult:
        shape_error = self._shape_error(action)
        if shape_error:
            return ActionValidationResult(valid=False, reason=shape_error)

        if not self.capabilities.supports(adapter_name, action.type):
            return ActionValidationResult(
                valid=False,
                reason=f"Adapter '{adapter_name}' does not support action '{action.type.value}'.",
                normalized_action=self._fallback_action(action),
            )

        return ActionValidationResult(valid=True, normalized_action=action)

    def _shape_error(self, action: UserAction) -> str:
        if action.type == ActionType.send_text and not action.text:
            return "SEND_TEXT requires text."
        if action.type in {ActionType.click_option, ActionType.click_button, ActionType.select_dropdown, ActionType.open_link}:
            if not (action.target or action.value):
                return f"{action.type.value} requires target or value."
        if action.type in {ActionType.upload_file, ActionType.upload_document} and not action.file:
            return f"{action.type.value} requires file."
        if action.type == ActionType.select_date and not action.value:
            return "SELECT_DATE requires value."
        if action.type == ActionType.select_time and not action.value:
            return "SELECT_TIME requires value."
        if action.type == ActionType.dtmf and not action.value:
            return "DTMF requires value."
        return ""

    def _fallback_action(self, action: UserAction) -> UserAction:
        text = action.text or action.value or action.target
        if not text:
            text = "I need help continuing."
        return UserAction(type=ActionType.send_text, text=text)
