"""
Generic models for interactive agent responses and simulated user actions.

These models are vendor-neutral and intentionally unused by runtime execution
until later User Action Engine phases. They use standard-library dataclasses
to keep the Phase 1 foundation lightweight and dependency-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class InteractiveElementType(str, Enum):
    text = "text"
    button = "button"
    quick_reply = "quick_reply"
    suggestion_chip = "suggestion_chip"
    card = "card"
    dropdown = "dropdown"
    dropdown_option = "dropdown_option"
    menu_item = "menu_item"
    form = "form"
    form_field = "form_field"
    upload_request = "upload_request"
    confirmation = "confirmation"
    date_picker = "date_picker"
    time_picker = "time_picker"
    link = "link"
    unknown = "unknown"


class ActionType(str, Enum):
    send_text = "SEND_TEXT"
    click_option = "CLICK_OPTION"
    click_button = "CLICK_BUTTON"
    select_dropdown = "SELECT_DROPDOWN"
    upload_file = "UPLOAD_FILE"
    upload_document = "UPLOAD_DOCUMENT"
    select_date = "SELECT_DATE"
    select_time = "SELECT_TIME"
    confirm = "CONFIRM"
    cancel = "CANCEL"
    wait = "WAIT"
    dtmf = "DTMF"
    open_link = "OPEN_LINK"
    escalate = "ESCALATE"


def _strip_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


@dataclass
class InteractiveElement:
    type: InteractiveElementType
    label: str
    value: Optional[str] = None
    group: Optional[str] = None
    required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.label = self.label.strip() if self.label else ""
        if not self.label:
            raise ValueError("InteractiveElement.label is required.")
        self.value = _strip_optional(self.value)
        self.group = _strip_optional(self.group)

    def action_value(self) -> str:
        return self.value or self.label


@dataclass
class NormalizedAgentResponse:
    text: str = ""
    interactive: list[InteractiveElement] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_interactive_content(self) -> bool:
        return bool(self.interactive)


@dataclass
class UserAction:
    type: ActionType
    target: Optional[str] = None
    text: Optional[str] = None
    value: Optional[str] = None
    file: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.target = _strip_optional(self.target)
        self.text = _strip_optional(self.text)
        self.value = _strip_optional(self.value)
        self.file = _strip_optional(self.file)


@dataclass
class ActionValidationResult:
    valid: bool
    reason: str = ""
    normalized_action: Optional[UserAction] = None
