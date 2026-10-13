"""
Universal form field type vocabulary.
"""

from __future__ import annotations

from enum import Enum


class FieldType(str, Enum):
    text = "TEXT"
    textarea = "TEXTAREA"
    email = "EMAIL"
    phone = "PHONE"
    number = "NUMBER"
    password = "PASSWORD"
    otp = "OTP"
    date = "DATE"
    time = "TIME"
    datetime = "DATETIME"
    search = "SEARCH"
    url = "URL"
    address = "ADDRESS"
    dropdown = "DROPDOWN"
    radio = "RADIO"
    checkbox = "CHECKBOX"
    multiselect = "MULTISELECT"
    upload_file = "UPLOAD_FILE"
    upload_image = "UPLOAD_IMAGE"
    hidden = "HIDDEN"
    custom = "CUSTOM"


SUPPORTED_FIELD_TYPES: tuple[FieldType, ...] = tuple(FieldType)
