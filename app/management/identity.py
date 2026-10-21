"""Resolve provider-neutral agent identities without exposing configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable

from app.connections.storage import repository
from app.management.models import AgentIdentity


_ROOT = Path(__file__).resolve().parents[2]
_CALLING_STORE = _ROOT / "calling_connections.json"
_KNOWN_NAMESPACES = {"chatbot", "voice", "calling", "legacy"}


def make_agent_key(agent_type: str | None, connection_id: str) -> str:
    namespace = str(agent_type or "legacy").strip().lower()
    if namespace not in _KNOWN_NAMESPACES:
        namespace = "legacy"
    return f"{namespace}:{connection_id}"


def split_agent_key(agent_key: str) -> tuple[str, str]:
    namespace, separator, connection_id = agent_key.partition(":")
    if not separator or namespace not in _KNOWN_NAMESPACES or not connection_id:
        raise ValueError("Invalid agent key")
    return namespace, connection_id


class AgentIdentityResolver:
    """Merge safe identities from connection stores and orphan evaluations."""

    def __init__(
        self,
        connection_loader: Callable[[], Iterable[Any]] | None = None,
        calling_store_path: Path | None = None,
    ) -> None:
        self._connection_loader = connection_loader or repository.list_all
        self._calling_store_path = calling_store_path or _CALLING_STORE

    def resolve_all(self, evaluations: Iterable[dict[str, Any]]) -> dict[str, AgentIdentity]:
        identities = self._connection_identities()
        identities.update(self._calling_identities())
        for report in evaluations:
            connection_id = _connection_id(report)
            if not connection_id:
                continue
            agent_type = _evaluation_agent_type(report)
            key = make_agent_key(agent_type, connection_id)
            if key not in identities:
                identities[key] = AgentIdentity(
                    agent_key=key,
                    connection_id=connection_id,
                    name=f"Deleted or unavailable agent ({connection_id})",
                    agent_type=agent_type,
                    adapter=_text(report.get("adapter")),
                    provider=_text(report.get("provider") or report.get("adapter")),
                    connection_status="missing",
                )
        return identities

    def _connection_identities(self) -> dict[str, AgentIdentity]:
        result: dict[str, AgentIdentity] = {}
        for connection in self._connection_loader():
            agent_type = str(getattr(connection.type, "value", connection.type)).lower()
            key = make_agent_key(agent_type, connection.id)
            result[key] = AgentIdentity(
                agent_key=key,
                connection_id=connection.id,
                name=connection.name,
                agent_type=agent_type,
                adapter=connection.adapter,
                provider=connection.adapter,
                connection_status="available",
            )
        return result

    def _calling_identities(self) -> dict[str, AgentIdentity]:
        if not self._calling_store_path.exists():
            return {}
        try:
            data = json.loads(self._calling_store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        result: dict[str, AgentIdentity] = {}
        for fallback_id, raw in data.items():
            if not isinstance(raw, dict):
                continue
            connection_id = _text(raw.get("id") or fallback_id)
            if not connection_id:
                continue
            key = make_agent_key("calling", connection_id)
            result[key] = AgentIdentity(
                agent_key=key,
                connection_id=connection_id,
                name=_text(raw.get("name")) or connection_id,
                agent_type="calling",
                adapter=_text(raw.get("provider")),
                provider=_text(raw.get("provider")),
                connection_status="available",
            )
        return result


def evaluation_matches_agent(report: dict[str, Any], agent_key: str) -> bool:
    namespace, connection_id = split_agent_key(agent_key)
    if _connection_id(report) != connection_id:
        return False
    report_type = _evaluation_agent_type(report)
    return namespace == report_type or (namespace == "legacy" and report_type == "legacy")


def _connection_id(report: dict[str, Any]) -> str | None:
    return _text(report.get("connection_id") or report.get("agent_id"))


def _evaluation_agent_type(report: dict[str, Any]) -> str:
    value = str(report.get("agent_type") or "").strip().lower()
    if value in {"chatbot", "voice", "calling"}:
        return value
    if str(report.get("provider") or "").strip().lower() in {
        "vapi", "twilio", "retell", "bland", "sip"
    }:
        return "calling"
    return "legacy"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
