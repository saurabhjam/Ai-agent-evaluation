"""
State vocabulary for universal chatbot forms.
"""

from __future__ import annotations

from enum import Enum


class FormSubmissionState(str, Enum):
    not_ready = "NOT_READY"
    ready = "READY"
    submitting = "SUBMITTING"
    submitted = "SUBMITTED"
    failed = "FAILED"


class FieldValidationType(str, Enum):
    required = "REQUIRED"
    optional = "OPTIONAL"
    regex = "REGEX"
    min_length = "MINIMUM_LENGTH"
    max_length = "MAXIMUM_LENGTH"
    range = "RANGE"
    email = "EMAIL"
    phone = "PHONE"
    number = "NUMBER"
    custom = "CUSTOM"
