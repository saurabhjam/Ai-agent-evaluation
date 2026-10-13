from __future__ import annotations

import re
from typing import Any

from app.models.conversation import RAGEvidence


def get_values_by_path(data: Any, path: str) -> list[Any]:
    if not path:
        return []
    normalized = re.sub(r"\[\*\]", "[]", path)
    parts = [part for part in normalized.split(".") if part]
    values = _values_by_parts(data, parts)
    flattened: list[Any] = []
    for value in values:
        if isinstance(value, list):
            flattened.extend(value)
        else:
            flattened.append(value)
    return [value for value in flattened if value is not None and value != ""]


def extract_rag_evidence(data: dict[str, Any], config: dict[str, Any]) -> RAGEvidence | None:
    rag_config = config.get("rag_config") or config.get("rag") or {}
    response_mapping = config.get("response_mapping") or {}
    mapping_rag = response_mapping.get("rag") if isinstance(response_mapping.get("rag"), dict) else {}

    effective = {**mapping_rag, **rag_config}
    if not effective:
        return None
    if effective.get("enabled") is False:
        return None

    context_path = (
        effective.get("context_path")
        or effective.get("contexts_path")
        or effective.get("retrieved_context_path")
    )
    if not context_path:
        return None

    contexts: list[str] = []
    seen_contexts: set[str] = set()
    for value in get_values_by_path(data, context_path):
        context = _normalise_context_value(value)
        if context and context not in seen_contexts:
            seen_contexts.add(context)
            contexts.append(context)

    citation_path = effective.get("citation_path") or effective.get("citations_path")
    citations = get_values_by_path(data, citation_path) if citation_path else []

    if not contexts:
        return None

    metadata = {
        key: value
        for key, value in effective.items()
        if key not in {"enabled", "context_path", "contexts_path", "retrieved_context_path", "citation_path", "citations_path"}
    }

    return RAGEvidence(
        available=True,
        source=str(effective.get("source_type") or effective.get("source") or "agent_retrieval"),
        contexts=contexts,
        citations=citations or None,
        metadata=metadata or None,
    )


def _values_by_parts(current: Any, parts: list[str]) -> list[Any]:
    if not parts:
        return [current]
    part = parts[0]
    remaining = parts[1:]

    if part.endswith("[]"):
        key = part[:-2]
        if isinstance(current, dict):
            current = current.get(key)
        if not isinstance(current, list):
            return []
        values: list[Any] = []
        for item in current:
            values.extend(_values_by_parts(item, remaining))
        return values

    if isinstance(current, dict):
        if part not in current:
            return []
        return _values_by_parts(current[part], remaining)

    if isinstance(current, list) and part.isdigit():
        index = int(part)
        if 0 <= index < len(current):
            return _values_by_parts(current[index], remaining)

    return []


def _normalise_context_value(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        for key in ("content", "text", "chunk", "snippet", "page_content"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return None
