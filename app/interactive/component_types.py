"""
Universal chatbot UI component type vocabulary.

Components describe what a chatbot displays. They are intentionally separate
from interactions, which describe what EvalForge chooses to do next.
"""

from __future__ import annotations

from enum import Enum


class ComponentType(str, Enum):
    text = "TEXT"
    button = "BUTTON"
    quick_reply = "QUICK_REPLY"
    dropdown = "DROPDOWN"
    checkbox = "CHECKBOX"
    radio_button = "RADIO_BUTTON"
    date_picker = "DATE_PICKER"
    time_picker = "TIME_PICKER"
    email_input = "EMAIL_INPUT"
    phone_input = "PHONE_INPUT"
    number_input = "NUMBER_INPUT"
    otp_input = "OTP_INPUT"
    search_box = "SEARCH_BOX"
    text_area = "TEXT_AREA"
    image = "IMAGE"
    document = "DOCUMENT"
    upload = "UPLOAD"
    link = "LINK"
    card = "CARD"
    carousel = "CAROUSEL"
    list = "LIST"
    table = "TABLE"
    markdown = "MARKDOWN"
    html = "HTML"
    unknown = "UNKNOWN"


SUPPORTED_COMPONENT_TYPES: tuple[ComponentType, ...] = tuple(ComponentType)
