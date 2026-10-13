"""Backend validation data models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


class BackendRequest(BaseModel):
    validator_type: str = "rest"
    config: dict[str, Any] = Field(default_factory=dict)


class BackendEvidence(BaseModel):
    name: str
    expected: Optional[Any] = None
    actual: Optional[Any] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BackendValidationCheck(BaseModel):
    name: str
    passed: bool
    reason: str
    expected: Optional[Any] = None
    actual: Optional[Any] = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class BackendValidationSummary(BaseModel):
    status: str
    passed: Optional[bool] = None
    reason: str
    checks: list[BackendValidationCheck] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


BackendValidationResult = BackendValidationSummary
