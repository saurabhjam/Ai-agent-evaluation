"""Deterministic, provider-neutral evidence analysis for completed evaluations."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


def _value(item: Any, key: str, default: Any = None) -> Any:
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def _message_id(message: Any, index: int) -> str:
    return str(_value(message, "message_id") or _value(message, "id") or f"ef-message-{index}")


class EvidenceAssessment(BaseModel):
    kind: Literal["factual_claim", "contradiction", "numerical"]
    status: Literal["supported", "contradicted", "unsupported", "unverified"]
    message_ids: list[str] = Field(default_factory=list)
    claim: str | None = None
    expected: Any = None
    actual: Any = None
    details: dict[str, Any] = Field(default_factory=dict)


class TechnicalErrorEvidence(BaseModel):
    category: Literal[
        "authentication", "authorization", "rate_limit", "service_failure",
        "timeout", "connection", "tool_execution", "unknown",
    ]
    origin: Literal["agent_observed", "evaluation_infrastructure", "integration"]
    message: str
    status_code: int | None = None
    conversation_message_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


def assess_factual_claims(transcript: list[Any]) -> list[EvidenceAssessment]:
    """Assess adapter/evaluator supplied factual claims without inventing ground truth."""
    assessments: list[EvidenceAssessment] = []
    for index, message in enumerate(transcript or []):
        metadata = _value(message, "metadata") or {}
        claims = metadata.get("factual_claims") if isinstance(metadata, dict) else None
        for claim in claims or []:
            if not isinstance(claim, dict):
                continue
            explicit = str(claim.get("status") or claim.get("evidence_status") or "").lower()
            expected_present = "expected" in claim or "reference_value" in claim
            expected = claim.get("expected", claim.get("reference_value"))
            actual = claim.get("actual", claim.get("value"))
            if explicit in {"supported", "contradicted", "unsupported", "unverified"}:
                status = explicit
            elif expected_present:
                status = "supported" if _comparable_equal(actual, expected) else "contradicted"
            elif claim.get("evidence_available") is True:
                status = "unsupported"
            else:
                status = "unverified"
            assessments.append(EvidenceAssessment(
                kind="factual_claim",
                status=status,
                message_ids=[_message_id(message, index)],
                claim=str(claim.get("claim") or claim.get("attribute") or "Factual claim"),
                expected=expected,
                actual=actual,
                details={key: value for key, value in claim.items() if key not in {"expected", "reference_value", "actual", "value"}},
            ))
    return assessments


def classify_technical_errors(
    transcript: list[Any] | None = None,
    execution_error: str | None = None,
) -> list[TechnicalErrorEvidence]:
    findings: list[TechnicalErrorEvidence] = []
    if execution_error:
        finding = _classify_error_text(execution_error, origin="evaluation_infrastructure")
        if finding:
            findings.append(finding)
    for index, message in enumerate(transcript or []):
        metadata = _value(message, "metadata") or {}
        role = _value(message, "role")
        candidates: list[tuple[str, str]] = []
        if isinstance(metadata, dict):
            for key in ("error", "adapter_error", "tool_error", "backend_error"):
                if metadata.get(key):
                    candidates.append((str(metadata[key]), "agent_observed" if role == "agent" else "integration"))
            for call in metadata.get("tool_calls") or []:
                if isinstance(call, dict) and call.get("error"):
                    candidates.append((str(call["error"]), "agent_observed"))
        content = str(_value(message, "content") or "")
        if role == "agent" and _looks_like_explicit_error(content):
            candidates.append((content, "agent_observed"))
        for text, origin in candidates:
            finding = _classify_error_text(text, origin=origin)
            if finding:
                finding.conversation_message_id = _message_id(message, index)
                findings.append(finding)
    unique: dict[tuple[Any, ...], TechnicalErrorEvidence] = {}
    for finding in findings:
        key = (finding.category, finding.origin, finding.status_code, finding.conversation_message_id, finding.message)
        unique[key] = finding
    return list(unique.values())


def detect_structured_contradictions(transcript: list[Any]) -> list[EvidenceAssessment]:
    """Confirm contradictions only for normalized claims with compatible dimensions."""
    claims: list[tuple[dict[str, Any], str]] = []
    for index, message in enumerate(transcript or []):
        metadata = _value(message, "metadata") or {}
        for claim in metadata.get("claims", []) if isinstance(metadata, dict) else []:
            if isinstance(claim, dict):
                claims.append((claim, _message_id(message, index)))
    findings: list[EvidenceAssessment] = []
    for left_index, (left, left_id) in enumerate(claims):
        for right, right_id in claims[left_index + 1:]:
            if not _claims_compatible(left, right):
                continue
            if right.get("is_correction") or right.get("is_update") or left.get("is_correction") or left.get("is_update"):
                continue
            if _comparable_equal(left.get("value"), right.get("value")):
                continue
            findings.append(EvidenceAssessment(
                kind="contradiction",
                status="contradicted",
                message_ids=[left_id, right_id],
                claim=str(left.get("attribute") or "Structured claim"),
                expected=left.get("value"),
                actual=right.get("value"),
                details={
                    key: left.get(key)
                    for key in ("entity", "attribute", "scope", "filters", "timeframe", "unit", "currency")
                    if left.get(key) is not None
                },
            ))
    return findings


def validate_numerical_evidence(transcript: list[Any]) -> list[EvidenceAssessment]:
    findings: list[EvidenceAssessment] = []
    for index, message in enumerate(transcript or []):
        metadata = _value(message, "metadata") or {}
        components = metadata.get("components", []) if isinstance(metadata, dict) else []
        tables = [component for component in components if isinstance(component, dict) and component.get("type") == "table"]
        claims = list(metadata.get("numerical_claims") or []) if isinstance(metadata, dict) else []
        if not claims:
            match = re.search(r"\b(?:found|showing|returned)\s+(\d+)\s+(?:records?|results?|rows?|items?)\b", str(_value(message, "content") or ""), re.I)
            if match:
                claims.append({"operation": "count", "claimed_value": int(match.group(1))})
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            table = _matching_table(tables, claim)
            message_id = _message_id(message, index)
            if table is None or not _table_is_complete(table):
                findings.append(_numerical_result("unverified", claim, message_id, None, "Table is absent, partial, paginated, or not marked complete."))
                continue
            rows = table.get("rows")
            if not isinstance(rows, list):
                findings.append(_numerical_result("unverified", claim, message_id, None, "Table rows are not reliably parseable."))
                continue
            calculated, reason = _calculate_table_value(rows, claim)
            if calculated is None:
                findings.append(_numerical_result("unverified", claim, message_id, None, reason))
                continue
            claimed = claim.get("claimed_value", claim.get("value"))
            status = "supported" if _numbers_equal(claimed, calculated) else "contradicted"
            findings.append(_numerical_result(status, claim, message_id, calculated, reason))
    return findings


def _classify_error_text(text: str, *, origin: str) -> TechnicalErrorEvidence | None:
    lowered = str(text or "").lower()
    status_match = re.search(r"(?:http\s*)?\b(401|403|429|500|502|503)\b", lowered)
    status = int(status_match.group(1)) if status_match else None
    if status == 401 or "authentication failed" in lowered or "invalid token" in lowered:
        category = "authentication"
    elif status == 403 or "forbidden" in lowered or "authorization failed" in lowered:
        category = "authorization"
    elif status == 429 or "rate limit" in lowered:
        category = "rate_limit"
    elif status in {500, 502, 503} or "service unavailable" in lowered or "bad gateway" in lowered:
        category = "service_failure"
    elif "timeout" in lowered or "timed out" in lowered:
        category = "timeout"
    elif "connection" in lowered and any(word in lowered for word in ("failed", "closed", "refused", "reset")):
        category = "connection"
    elif any(phrase in lowered for phrase in ("tool error", "tool execution", "backend execution")):
        category = "tool_execution"
    else:
        return None
    return TechnicalErrorEvidence(category=category, origin=origin, message=str(text), status_code=status)


def _looks_like_explicit_error(text: str) -> bool:
    lowered = str(text or "").lower()
    return bool(re.search(r"\b(?:http\s*)?(?:401|403|429|500|502|503)\b", lowered)) or any(
        phrase in lowered for phrase in ("authentication failed", "authorization failed", "rate limit", "service unavailable", "request timed out", "tool execution error")
    )


def _claims_compatible(left: dict[str, Any], right: dict[str, Any]) -> bool:
    required = ("entity", "attribute")
    if any(left.get(key) in (None, "") or right.get(key) in (None, "") for key in required):
        return False
    dimensions = ("entity", "attribute", "scope", "filters", "timeframe", "unit", "currency")
    return all(_normalized_dimension(left.get(key)) == _normalized_dimension(right.get(key)) for key in dimensions)


def _normalized_dimension(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((str(key), _normalized_dimension(item)) for key, item in value.items()))
    if isinstance(value, list):
        return tuple(_normalized_dimension(item) for item in value)
    return str(value).strip().lower() if value is not None else None


def _comparable_equal(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return _numbers_equal(left, right)
    return _normalized_dimension(left) == _normalized_dimension(right)


def _numbers_equal(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) <= 1e-9
    except (TypeError, ValueError):
        return False


def _matching_table(tables: list[dict[str, Any]], claim: dict[str, Any]) -> dict[str, Any] | None:
    table_id = claim.get("table_id")
    if table_id:
        return next((table for table in tables if table.get("id") == table_id), None)
    return tables[0] if len(tables) == 1 else None


def _table_is_complete(table: dict[str, Any]) -> bool:
    if table.get("complete") is True or table.get("is_complete") is True:
        return True
    pagination = table.get("pagination")
    return isinstance(pagination, dict) and pagination.get("has_more") is False and pagination.get("truncated") is not True


def _calculate_table_value(rows: list[Any], claim: dict[str, Any]) -> tuple[float | int | None, str]:
    operation = str(claim.get("operation") or "count").lower()
    if operation == "count":
        return len(rows), "Counted complete table rows."
    field = claim.get("field")
    if not field or not all(isinstance(row, dict) and field in row for row in rows):
        return None, "The requested numeric field is missing from one or more rows."
    expected_unit = claim.get("unit") or claim.get("currency")
    observed_units = {
        row.get(f"{field}_unit") or row.get("unit") or row.get("currency")
        for row in rows if isinstance(row, dict)
    } - {None, ""}
    if len(observed_units) > 1 or (expected_unit and observed_units and _normalized_dimension(expected_unit) not in {_normalized_dimension(unit) for unit in observed_units}):
        return None, "Rows use mixed or incompatible units/currencies."
    try:
        values = [float(row[field]) for row in rows]
    except (TypeError, ValueError):
        return None, "One or more values are not reliably numeric."
    if not values:
        return None, "No numeric values are available."
    if operation == "sum":
        return sum(values), "Summed values from the complete table."
    if operation == "average":
        return sum(values) / len(values), "Averaged values from the complete table."
    return None, f"Unsupported numerical operation: {operation}."


def _numerical_result(status: str, claim: dict[str, Any], message_id: str, calculated: Any, reason: str) -> EvidenceAssessment:
    return EvidenceAssessment(
        kind="numerical",
        status=status,
        message_ids=[message_id],
        claim=str(claim.get("operation") or "count"),
        expected=calculated,
        actual=claim.get("claimed_value", claim.get("value")),
        details={"field": claim.get("field"), "unit": claim.get("unit"), "currency": claim.get("currency"), "reason": reason},
    )
