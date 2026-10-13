"""
Pluggable registry for supported chatbot interaction types.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.interactive.interaction_types import InteractionType, SUPPORTED_INTERACTION_TYPES


@dataclass(frozen=True)
class InteractionDefinition:
    type: InteractionType
    handler_name: str
    description: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.handler_name.strip():
            raise ValueError("InteractionDefinition.handler_name is required.")


class InteractionRegistry:
    def __init__(self) -> None:
        self._definitions: dict[InteractionType, InteractionDefinition] = {}

    def register(self, definition: InteractionDefinition, *, overwrite: bool = False) -> None:
        if not isinstance(definition.type, InteractionType):
            object.__setattr__(definition, "type", InteractionType(definition.type))
        if definition.type in self._definitions and not overwrite:
            raise ValueError(f"Interaction type '{definition.type.value}' is already registered.")
        self._definitions[definition.type] = definition

    def get(self, interaction_type: InteractionType | str) -> InteractionDefinition:
        normalized = interaction_type if isinstance(interaction_type, InteractionType) else InteractionType(interaction_type)
        if normalized not in self._definitions:
            raise KeyError(f"Interaction type '{normalized.value}' is not registered.")
        return self._definitions[normalized]

    def has(self, interaction_type: InteractionType | str) -> bool:
        try:
            normalized = interaction_type if isinstance(interaction_type, InteractionType) else InteractionType(interaction_type)
        except ValueError:
            return False
        return normalized in self._definitions

    def list_types(self) -> list[InteractionType]:
        return sorted(self._definitions.keys(), key=lambda item: item.value)


def default_interaction_registry() -> InteractionRegistry:
    registry = InteractionRegistry()
    handler_names = {
        InteractionType.text: "send_text",
        InteractionType.button: "click_button",
        InteractionType.quick_reply: "click_quick_reply",
        InteractionType.dropdown: "select_option",
        InteractionType.checkbox: "toggle_checkbox",
        InteractionType.radio_button: "select_radio_button",
        InteractionType.date_picker: "select_date",
        InteractionType.time_picker: "select_time",
        InteractionType.email_input: "send_text",
        InteractionType.phone_input: "send_text",
        InteractionType.number_input: "send_text",
        InteractionType.otp_input: "enter_otp",
        InteractionType.search_box: "search",
        InteractionType.confirm: "confirm",
        InteractionType.cancel: "cancel",
        InteractionType.wait: "wait",
        InteractionType.upload_file: "upload_file",
        InteractionType.upload_image: "upload_image",
        InteractionType.custom_action: "execute_custom_action",
    }
    for interaction_type in SUPPORTED_INTERACTION_TYPES:
        registry.register(
            InteractionDefinition(
                type=interaction_type,
                handler_name=handler_names[interaction_type],
                description=f"Universal {interaction_type.value} chatbot interaction.",
            )
        )
    return registry
