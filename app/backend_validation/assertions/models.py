"""Assertion result models for backend validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AssertionResult(BaseModel):
    status: str
    passed: bool | None = None
    jsonpath: str
    operator: str
    expected: Any = None
    actual: Any = None
    message: str
