from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any
from uuid import uuid4

from app.models.connection import AgentConnection
from app.session.browser_session import BrowserSession

logger = logging.getLogger(__name__)


@dataclass
class EvaluationSession:
    """
    Runtime container for per-evaluation state.

    Phase 1 intentionally keeps this as a structural shim. It records the
    connection and auth provider used by the existing runtime without changing
    how authentication is created, refreshed, or cleaned up.
    """

    evaluation_id: str
    connection: AgentConnection
    browser_session: BrowserSession
    auth_provider: Any | None = None

    @classmethod
    def create(
        cls,
        connection: AgentConnection,
        browser_session: BrowserSession,
    ) -> "EvaluationSession":
        return cls(
            evaluation_id=f"eval_{uuid4().hex}",
            connection=connection,
            browser_session=browser_session,
        )

    def cleanup(self) -> None:
        cleanup = getattr(self.auth_provider, "cleanup", None)
        if callable(cleanup):
            cleanup()
        try:
            self.browser_session.close()
        except Exception:
            logger.exception("EvaluationSession browser cleanup failed.")
