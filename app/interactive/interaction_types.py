"""
Universal chatbot interaction type vocabulary.

This module is intentionally provider-neutral. It describes what kind of UI
interaction EvalForge wants to perform, not how any browser, REST, or vendor
adapter performs it.
"""

from __future__ import annotations

from enum import Enum


class InteractionType(str, Enum):
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
    confirm = "CONFIRM"
    cancel = "CANCEL"
    wait = "WAIT"
    upload_file = "UPLOAD_FILE"
    upload_image = "UPLOAD_IMAGE"
    custom_action = "CUSTOM_ACTION"


SUPPORTED_INTERACTION_TYPES: tuple[InteractionType, ...] = tuple(InteractionType)
