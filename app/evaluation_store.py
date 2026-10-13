"""Persistent storage for completed evaluation reports."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from typing import Any

from app.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_reports (
    evaluation_id TEXT PRIMARY KEY,
    connection_id TEXT,
    provider TEXT,
    scenario_id TEXT,
    session_id TEXT,
    provider_call_id TEXT,
    started_at TEXT,
    ended_at TEXT,
    duration_seconds REAL,
    status TEXT,
    overall_score REAL,
    passed INTEGER,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evaluation_reports_created_at
ON evaluation_reports(created_at);
CREATE INDEX IF NOT EXISTS idx_evaluation_reports_connection_id
ON evaluation_reports(connection_id);
"""


@contextmanager
def _conn():
    conn = sqlite3.connect(settings.db_path)
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def new_evaluation_id() -> str:
    return f"eval_{uuid.uuid4().hex}"


def save_evaluation_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a complete evaluation report payload and return the saved payload."""
    record = dict(payload)
    evaluation_id = str(record.get("evaluation_id") or new_evaluation_id())
    record["evaluation_id"] = evaluation_id

    with _conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO evaluation_reports (
                evaluation_id,
                connection_id,
                provider,
                scenario_id,
                session_id,
                provider_call_id,
                started_at,
                ended_at,
                duration_seconds,
                status,
                overall_score,
                passed,
                created_at,
                payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation_id,
                _string_or_none(record.get("connection_id") or record.get("agent_id")),
                _string_or_none(record.get("provider") or record.get("adapter")),
                _string_or_none(record.get("scenario_id")),
                _string_or_none(record.get("session_id")),
                _string_or_none(record.get("provider_call_id")),
                _string_or_none(record.get("started_at")),
                _string_or_none(record.get("ended_at")),
                _float_or_none(record.get("duration_seconds") or record.get("duration")),
                _string_or_none(record.get("status")),
                _float_or_none(record.get("overall_score")),
                _bool_int_or_none(record.get("passed")),
                _string_or_none(record.get("created_at")) or "",
                json.dumps(record, sort_keys=True),
            ),
        )
    return record


def get_evaluation_report(evaluation_id: str) -> dict[str, Any] | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT payload FROM evaluation_reports WHERE evaluation_id = ?",
            (evaluation_id,),
        ).fetchone()
    return json.loads(row[0]) if row else None


def list_evaluation_reports(connection_id: str | None = None) -> list[dict[str, Any]]:
    with _conn() as conn:
        if connection_id:
            rows = conn.execute(
                "SELECT payload FROM evaluation_reports WHERE connection_id = ? ORDER BY created_at DESC",
                (connection_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT payload FROM evaluation_reports ORDER BY created_at DESC"
            ).fetchall()
    return [json.loads(row[0]) for row in rows]


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    return int(bool(value))
