"""Session context generated during calling execution."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.calling.models import CallDirection, CallSession


class CallingSessionContext(BaseModel):
    """Provider/session details for one runtime call execution."""

    session: Optional[CallSession] = None
    direction: CallDirection = CallDirection.outbound
    to_number: str = "+15550000002"
    from_number: str = "+15550000001"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def session_id(self) -> Optional[str]:
        """Return the provider session id when present."""
        return self.session.session_id if self.session else None
