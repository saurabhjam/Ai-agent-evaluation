"""
Connection Storage — Universal Agent Connection System.

Provides a repository pattern for saving and retrieving client
agent configurations (AgentConnection).

Uses the existing SQLite database for persistence.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Optional

from app.models.connection import AgentConnection
from app.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_connections (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
"""

@contextmanager
def _conn():
    conn = sqlite3.connect(settings.db_path)
    try:
        conn.execute(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()

class ConnectionRepository:
    """
    Persistent repository for AgentConnection objects using SQLite.
    """

    def __init__(self) -> None:
        # Initialize schema
        with _conn() as conn:
            pass

    def save(self, connection: AgentConnection) -> None:
        with _conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO agent_connections (id, payload) VALUES (?, ?)",
                (connection.id, connection.model_dump_json())
            )

    def get(self, connection_id: str) -> Optional[AgentConnection]:
        with _conn() as conn:
            row = conn.execute(
                "SELECT payload FROM agent_connections WHERE id = ?", (connection_id,)
            ).fetchone()
            if not row:
                return None
            return AgentConnection.model_validate(json.loads(row[0]))

    def list_all(self) -> list[AgentConnection]:
        with _conn() as conn:
            rows = conn.execute("SELECT payload FROM agent_connections").fetchall()
            return [AgentConnection.model_validate(json.loads(r[0])) for r in rows]

    def delete(self, connection_id: str) -> bool:
        with _conn() as conn:
            cursor = conn.execute("DELETE FROM agent_connections WHERE id = ?", (connection_id,))
            return cursor.rowcount > 0

    def clear(self) -> None:
        """Clear all connections, primarily used for testing."""
        with _conn() as conn:
            conn.execute("DELETE FROM agent_connections")


# Global persistent instance for the API to use.
repository = ConnectionRepository()
