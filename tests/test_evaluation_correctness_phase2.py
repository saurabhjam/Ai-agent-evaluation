import json

import pytest

from app.evaluation_evidence import (
    assess_factual_claims,
    classify_technical_errors,
    detect_structured_contradictions,
    validate_numerical_evidence,
)
from app.evaluation_service import _balanced_overall_score
from app.evaluator import _apply_evidence_assessments
from app.report_engine import EvaluationReportEngine
from app.schemas import MetricResult


def _agent(content, *, message_id="agent-1", metadata=None, turn_index=1):
    return {"role": "agent", "content": content, "id": message_id, "turn_index": turn_index, "metadata": metadata or {}}


@pytest.mark.parametrize(
    "claim, expected_status",
    [
        ({"claim": "record count", "actual": 3, "expected": 3}, "supported"),
        ({"claim": "record count", "actual": 4, "expected": 3}, "contradicted"),
        ({"claim": "record count", "actual": 4}, "unverified"),
        ({"claim": "record count", "actual": 4, "evidence_available": True}, "unsupported"),
    ],
)
def test_factual_claim_evidence_states(claim, expected_status):
    result = assess_factual_claims([_agent("Result", metadata={"factual_claims": [claim]})])
    assert result[0].status == expected_status
    assert result[0].message_ids == ["agent-1"]


def test_clarification_and_technical_error_are_not_hallucinations():
    results = [MetricResult(name="Hallucination", score=1.0, passed=True, reason="", threshold=1.0, category="base")]
    transcript = [_agent("HTTP 502: service unavailable")]
    _apply_evidence_assessments(results, transcript)
    assert results[0].evaluation_status == "not_evaluated"
    assert results[0].evidence_status == "unverified"
    assert "classified separately" in results[0].reason

    clarification = [MetricResult(name="Hallucination", score=1.0, passed=True, reason="", threshold=1.0, category="base")]
    _apply_evidence_assessments(clarification, [_agent("Which account should I use?")])
    assert clarification[0].evaluation_status == "not_evaluated"
    assert clarification[0].evidence_status == "unverified"


@pytest.mark.parametrize(
    "text, category, status",
    [
        ("HTTP 401 invalid token", "authentication", 401),
        ("HTTP 403 forbidden", "authorization", 403),
        ("HTTP 429 rate limit exceeded", "rate_limit", 429),
        ("HTTP 502 bad gateway", "service_failure", 502),
        ("Adapter request timed out", "timeout", None),
        ("Connection refused", "connection", None),
        ("Tool execution error", "tool_execution", None),
    ],
)
def test_technical_error_categories(text, category, status):
    result = classify_technical_errors(execution_error=text)
    assert result[0].category == category
    assert result[0].status_code == status
    assert result[0].origin == "evaluation_infrastructure"


def test_agent_observed_and_infrastructure_errors_are_distinct():
    transcript = [_agent("I could not continue", metadata={"tool_error": "Tool execution error"})]
    agent_error = classify_technical_errors(transcript=transcript)[0]
    infrastructure_error = classify_technical_errors(execution_error="Adapter timeout")[0]
    assert agent_error.origin == "agent_observed"
    assert agent_error.conversation_message_id == "agent-1"
    assert infrastructure_error.origin == "evaluation_infrastructure"


def _claim(value, **overrides):
    result = {
        "entity": "entity-1",
        "attribute": "status",
        "scope": "all",
        "filters": {"state": "active"},
        "timeframe": "current",
        "value": value,
    }
    result.update(overrides)
    return result


def test_confirmed_structured_contradiction_preserves_message_ids():
    transcript = [
        _agent("First", message_id="a-1", metadata={"claims": [_claim(4)]}, turn_index=1),
        _agent("Second", message_id="a-2", metadata={"claims": [_claim(7)]}, turn_index=3),
    ]
    result = detect_structured_contradictions(transcript)
    assert len(result) == 1
    assert result[0].message_ids == ["a-1", "a-2"]


@pytest.mark.parametrize(
    "override",
    [
        {"timeframe": "previous"},
        {"entity": "entity-2"},
        {"scope": "subset"},
        {"filters": {"state": "closed"}},
        {"attribute": "count"},
    ],
)
def test_incompatible_claim_dimensions_are_not_contradictions(override):
    transcript = [
        _agent("First", message_id="a-1", metadata={"claims": [_claim(4)]}),
        _agent("Second", message_id="a-2", metadata={"claims": [_claim(7, **override)]}),
    ]
    assert detect_structured_contradictions(transcript) == []


def test_legitimate_correction_is_not_automatically_a_contradiction():
    transcript = [
        _agent("Initial", message_id="a-1", metadata={"claims": [_claim(4)]}),
        _agent("Correction", message_id="a-2", metadata={"claims": [_claim(7, is_correction=True)]}),
    ]
    assert detect_structured_contradictions(transcript) == []


def _table_message(claim, rows, *, complete=True, message="Summary", extra_table=None):
    table = {"type": "table", "id": "table-1", "rows": rows, "complete": complete}
    if extra_table:
        table.update(extra_table)
    return _agent(message, metadata={"components": [table], "numerical_claims": [claim]})


@pytest.mark.parametrize(
    "claim, rows, status, calculated",
    [
        ({"operation": "count", "claimed_value": 2}, [{"id": 1}, {"id": 2}], "supported", 2),
        ({"operation": "count", "claimed_value": 3}, [{"id": 1}, {"id": 2}], "contradicted", 2),
        ({"operation": "sum", "field": "amount", "claimed_value": 30}, [{"amount": 10}, {"amount": 20}], "supported", 30.0),
        ({"operation": "sum", "field": "amount", "claimed_value": 40}, [{"amount": 10}, {"amount": 20}], "contradicted", 30.0),
        ({"operation": "average", "field": "amount", "claimed_value": 15}, [{"amount": 10}, {"amount": 20}], "supported", 15.0),
        ({"operation": "average", "field": "amount", "claimed_value": 10}, [{"amount": 10}, {"amount": 20}], "contradicted", 15.0),
    ],
)
def test_deterministic_numerical_validation(claim, rows, status, calculated):
    result = validate_numerical_evidence([_table_message(claim, rows)])[0]
    assert result.status == status
    assert result.expected == calculated
    assert result.message_ids == ["agent-1"]


def test_plain_text_count_is_checked_against_complete_table():
    message = _agent(
        "Found 3 records.",
        metadata={"components": [{"type": "table", "rows": [{"id": 1}, {"id": 2}], "complete": True}]},
    )
    result = validate_numerical_evidence([message])[0]
    assert result.status == "contradicted"
    assert result.actual == 3
    assert result.expected == 2


def test_partial_table_and_mixed_currency_remain_unverified():
    partial = validate_numerical_evidence([
        _table_message({"operation": "count", "claimed_value": 10}, [{"id": 1}], complete=False)
    ])[0]
    mixed = validate_numerical_evidence([
        _table_message(
            {"operation": "sum", "field": "amount", "claimed_value": 30},
            [{"amount": 10, "currency": "USD"}, {"amount": 20, "currency": "EUR"}],
        )
    ])[0]
    assert partial.status == "unverified"
    assert mixed.status == "unverified"


def test_ambiguous_numeric_field_remains_unverified():
    result = validate_numerical_evidence([
        _table_message({"operation": "sum", "field": "amount", "claimed_value": 30}, [{"amount": 10}, {"other": 20}])
    ])[0]
    assert result.status == "unverified"


def test_confirmed_evidence_routes_to_only_relevant_metrics():
    metrics = [
        MetricResult(name=name, score=1.0, passed=True, reason="", threshold=1.0 if name == "Hallucination" else 0.75, category="base")
        for name in ("Hallucination", "Multi-turn Consistency", "Context Retention", "Goal Completion")
    ]
    transcript = [
        _agent("First", message_id="a-1", metadata={"claims": [_claim(4)]}, turn_index=1),
        _agent(
            "Found 3 records.", message_id="a-2", turn_index=3,
            metadata={
                "claims": [_claim(7)],
                "components": [{"type": "table", "rows": [{"id": 1}, {"id": 2}], "complete": True}],
            },
        ),
    ]
    _apply_evidence_assessments(metrics, transcript)
    by_name = {metric.name: metric for metric in metrics}
    assert by_name["Hallucination"].score == 0.55
    assert by_name["Multi-turn Consistency"].score == 0.55
    assert by_name["Context Retention"].score == 1.0
    assert by_name["Goal Completion"].score == 1.0
    assert by_name["Hallucination"].conversation_message_id == "a-2"
    assert by_name["Multi-turn Consistency"].conversation_message_id == "a-2"


def test_unavailable_metric_is_excluded_from_aggregation_and_reported():
    metrics = [
        MetricResult(name="Goal Completion", score=0.8, passed=True, reason="", category="base"),
        MetricResult(name="Hallucination", score=1.0, passed=True, reason="", category="base", evaluation_status="not_evaluated", evidence_status="unverified"),
    ]
    assert _balanced_overall_score(metrics) == 0.8
    report = EvaluationReportEngine().build({
        "overall_score": 0.8, "passed": True, "metrics": [metric.model_dump(mode="json") for metric in metrics], "conversation": [],
    })
    hallucination = next(item for item in report["scorecard"]["metrics"] if item["name"] == "Hallucination")
    assert hallucination["status"] == "NOT EVALUATED"
    assert report["scorecard"]["passed_metrics"] == 1
    assert report["scorecard"]["failed_metrics"] == 0


def test_report_preserves_technical_error_evidence():
    error = classify_technical_errors(execution_error="HTTP 401 invalid token")[0]
    report = EvaluationReportEngine().build({
        "overall_score": 0.0, "passed": False, "metrics": [], "conversation": [],
        "technical_errors": [error.model_dump(mode="json")],
    })
    assert report["technical_errors"][0]["category"] == "authentication"
    json.dumps(report)
