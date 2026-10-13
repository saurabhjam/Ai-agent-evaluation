"""
Vendor-neutral foundation for future interactive user action planning.

Phase 1 intentionally does not integrate with runtime execution.
"""

from app.interactive.models import (
    ActionType,
    ActionValidationResult,
    InteractiveElement,
    InteractiveElementType,
    NormalizedAgentResponse,
    UserAction,
)

__all__ = [
    "ActionType",
    "ActionValidationResult",
    "InteractiveElement",
    "InteractiveElementType",
    "NormalizedAgentResponse",
    "UserAction",
]
