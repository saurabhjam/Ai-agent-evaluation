"""Calling-only normalization for structured values heard in voice transcripts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import re
from typing import Any


@dataclass(frozen=True)
class StructuredValueEvidence:
    field: str
    expected_raw: str
    observed_raw: str
    expected_normalized: str | None
    observed_normalized: str | None
    semantic_match: bool | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def compare_structured_value(field: str, expected: Any, observed: Any) -> StructuredValueEvidence:
    expected_raw, observed_raw = str(expected), str(observed)
    left = normalize_structured_value(field, expected_raw)
    right = normalize_structured_value(field, observed_raw)
    match = left == right if left is not None and right is not None else None
    return StructuredValueEvidence(field, expected_raw, observed_raw, left, right, match)


def normalize_structured_value(field: str, value: Any) -> str | None:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return None
    kind = _field_kind(field)
    if kind == "phone":
        digits = re.sub(r"\D", "", text)
        return digits if 7 <= len(digits) <= 15 else None
    if kind == "time":
        return _normalize_time(text)
    if kind == "date":
        return _normalize_date(text)
    if kind == "name":
        cleaned = re.sub(r"[^a-z\s'-]", "", text.casefold())
        return " ".join(cleaned.split()) or None
    return text.casefold()


def calling_evidence_instructions(persona: Any, transcript: list[Any]) -> tuple[str, list[dict[str, Any]]]:
    """Build deterministic evidence without altering the captured transcript."""
    raw = persona.model_dump(mode="json") if hasattr(persona, "model_dump") else dict(persona or {})
    messages = [_message_text(item) for item in transcript]
    evidence: list[dict[str, Any]] = []
    lines: list[str] = []
    for field, expected in raw.items():
        if field in {"goal", "tone", "edge_case"} or expected in (None, ""):
            continue
        normalized = normalize_structured_value(field, expected)
        if normalized is None or _field_kind(field) not in {"phone", "time", "date", "name"}:
            continue
        matches = _observed_candidates(field, messages)
        field_evidence = [compare_structured_value(field, expected, value) for value in matches]
        evidence.extend(item.as_dict() for item in field_evidence)
        lines.append(f"- {field}: configured normalized value={normalized}.")
        for item in field_evidence:
            if item.semantic_match is True:
                lines.append(
                    f"- deterministic match: {field}, observed={item.observed_raw!r}, "
                    f"normalized={item.observed_normalized}, semantic_match=true; do not claim contradiction."
                )
    instructions = (
        "\nCalling-only deterministic evidence rules:\n"
        "Equivalent normalized structured values are not contradictions. "
        "A user supplying one requested field followed by the agent acknowledging it and requesting "
        "the next workflow field is valid progression; the agent need not repeat the supplied value.\n"
        + "\n".join(lines)
    )
    return instructions, evidence


def _field_kind(field: str) -> str:
    key = field.casefold().replace("-", "_")
    if any(token in key for token in ("phone", "mobile", "telephone", "contact_number")):
        return "phone"
    if "time" in key:
        return "time"
    if "date" in key or "day" in key:
        return "date"
    if "name" in key:
        return "name"
    return "other"


def _normalize_time(text: str) -> str | None:
    compact = re.sub(r"[.\s]", "", text.upper())
    match = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?(AM|PM)", compact)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    hour = (hour % 12) + (12 if match.group(3) == "PM" else 0)
    return f"{hour:02d}:{minute:02d}"


def _normalize_date(text: str) -> str | None:
    cleaned = re.sub(r"[.,]", " ", text)
    cleaned = " ".join(cleaned.split())
    for fmt in ("%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y", "%B %d", "%b %d", "%d %B", "%d %b"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.strftime("%Y-%m-%d") if "%Y" in fmt else parsed.strftime("--%m-%d")
        except ValueError:
            pass
    return None


def _observed_candidates(field: str, messages: list[str]) -> list[str]:
    kind = _field_kind(field)
    patterns = {
        "phone": r"(?<!\d)\d(?:[\d\s.()\-]{5,}\d)",
        "time": r"\b\d{1,4}(?::\d{2})?\s*[AP]\.?M\.?(?:\b|$)",
        "date": r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:[.,]?\s+\d{4})?\b|\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)(?:\s+\d{4})?\b",
    }
    if kind not in patterns:
        return []
    return [match.group(0) for text in messages for match in re.finditer(patterns[kind], text, re.I)]


def _message_text(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or message.get("message") or "")
    return str(getattr(message, "content", getattr(message, "message", "")) or "")
