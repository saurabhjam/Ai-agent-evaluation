"""
Minimal SQLite storage for POC purposes.

Swap for Postgres + SQLAlchemy when moving past the POC (Section 5/9 of the
R&D report call for Postgres at scale) — the interface (save_run / get_run /
list_runs) stays the same, so nothing above this layer needs to change.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from app.config import settings
from app.schemas import TestRunResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS test_runs (
    run_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    overall_score REAL NOT NULL,
    passed INTEGER NOT NULL,
    created_at TEXT NOT NULL,
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


def save_run(result: TestRunResult) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO test_runs "
            "(run_id, scenario_id, channel, overall_score, passed, created_at, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                result.run_id,
                result.scenario_id,
                result.agent.adapter,
                result.overall_score,
                int(result.passed),
                result.created_at,
                result.model_dump_json(),
            ),
        )


def get_run(run_id: str) -> TestRunResult | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT payload FROM test_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if not row:
            return None
        return TestRunResult.model_validate(json.loads(row[0]))


def list_runs(scenario_id: str | None = None) -> list[TestRunResult]:
    with _conn() as conn:
        if scenario_id:
            rows = conn.execute(
                "SELECT payload FROM test_runs WHERE scenario_id = ? ORDER BY created_at DESC",
                (scenario_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT payload FROM test_runs ORDER BY created_at DESC"
            ).fetchall()
        return [TestRunResult.model_validate(json.loads(r[0])) for r in rows]
