"""Deterministic consolidated reporting over persisted management evaluations."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from app.management.consolidated_models import (
    ConsolidatedEvaluationReference,
    ConsolidatedIssue,
    ConsolidatedMetric,
    ConsolidatedRecommendation,
    ConsolidatedReport,
    ReportSelection,
    ScenarioCoverage,
    ScenarioResult,
)
from app.management.service import ManagementAggregationService, _outcome, _score, _timestamp


SECTION_TITLES = [
    "1. Executive Summary and Overall Performance",
    "2. Evaluation Coverage and Run Information",
    "3. 10 Evaluation Metrics — Consolidated Scores",
    "4. Scenario-wise Results and Report Links",
    "5. Critical Failures and Evidence",
    "6. Recommendations and Improvement Priorities",
    "7. Historical Performance Comparison",
    "8. Individual Report References",
]

METRIC_NAMES = [
    "Goal Completion",
    "Persona and Tone Adherence",
    "Conversational Quality",
    "Context Retention",
    "Multi-turn Consistency",
    "Intent Understanding",
    "Answer Relevancy",
    "Hallucination",
    "Completeness",
    "Response Quality",
]

_METRIC_ALIASES = {
    "persona & tone": "Persona and Tone Adherence",
    "persona and tone": "Persona and Tone Adherence",
    "persona & tone adherence": "Persona and Tone Adherence",
    "intent detection": "Intent Understanding",
    "intent": "Intent Understanding",
}

_RECOMMENDATIONS = {
    "Goal Completion": "Review task completion and action-execution behavior for the affected scenarios.",
    "Persona and Tone Adherence": "Align response style with the configured persona and tone throughout each conversation.",
    "Conversational Quality": "Reduce repetition and unnecessary clarification while preserving a natural turn flow.",
    "Context Retention": "Investigate multi-turn context retention for the affected scenarios.",
    "Multi-turn Consistency": "Keep facts, decisions, and workflow state consistent across turns.",
    "Intent Understanding": "Improve intent routing and clarification decisions for the affected requests.",
    "Answer Relevancy": "Make responses directly address the latest user request and established context.",
    "Hallucination": "Review grounding and independent evidence for the affected factual claims.",
    "Completeness": "Ensure responses include every required part of the requested outcome.",
    "Response Quality": "Improve clarity, correctness, and usefulness of the affected responses.",
}

_SENSITIVE_KEY = re.compile(r"(token|password|secret|authorization|cookie|credential|api[_-]?key)", re.I)


class ConsolidatedReportEngine:
    """Build a report without executing evaluations or mutating persisted data."""

    def __init__(self, service: ManagementAggregationService | None = None) -> None:
        self._service = service or ManagementAggregationService()

    def build(
        self,
        agent_key: str,
        *,
        scenario_id: str | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> ConsolidatedReport:
        agent = self._service.get_agent(agent_key)
        reports = self._service.select_reports(
            agent_key, scenario_id=scenario_id, status=status, date_from=date_from, date_to=date_to
        )
        metrics = _metrics(reports)
        scenarios = _scenario_results(reports)
        failures = _issues(reports)
        recommendations = _recommendations(failures, metrics, reports)
        valid_scores = [_score(report) for report in reports if _outcome(report) in {"pass", "fail"}]
        valid_scores = [value for value in valid_scores if value is not None]
        counts = Counter(_outcome(report) for report in reports)
        timestamps = [value for value in (_timestamp(report) for report in reports) if value]
        strongest = max((metric for metric in metrics if metric.average_score is not None), key=lambda m: m.average_score, default=None)
        weakest = min((metric for metric in metrics if metric.average_score is not None), key=lambda m: m.average_score, default=None)
        quality_issues = Counter(issue.metric for issue in failures if not issue.technical and issue.metric)
        frequent = quality_issues.most_common(1)[0][0] if quality_issues else None
        summary = _performance_summary(agent.name, len(scenarios), len(reports), counts, _average(valid_scores))
        coverage = _coverage(reports, scenarios, metrics, timestamps, agent.comparability_warnings)
        references = [_reference(report) for report in reports]
        return ConsolidatedReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            agent_key=agent.agent_key,
            agent_name=agent.name,
            agent_type=agent.agent_type,
            provider=agent.provider,
            adapter=agent.adapter,
            selection=ReportSelection(
                scenario_id=scenario_id,
                status=status,
                date_from=date_from.isoformat() if date_from else None,
                date_to=date_to.isoformat() if date_to else None,
                included_evaluation_ids=[item.evaluation_id for item in references],
            ),
            section_order=SECTION_TITLES,
            executive_summary={
                "mean_selected_run_score": _average(valid_scores),
                "total_evaluation_runs": len(reports),
                "unique_scenarios": len(scenarios),
                "passed_runs": counts["pass"],
                "failed_runs": counts["fail"],
                "technical_errors": counts["error"],
                "unknown_outcomes": counts["unknown"],
                "selected_period": _period(timestamps),
                "performance_overview": summary,
                "strongest_evaluated_metric": strongest.name if strongest else None,
                "weakest_evaluated_metric": weakest.name if weakest else None,
                "most_frequent_quality_issue": frequent,
                "technical_reliability": f"{counts['error']} of {len(reports)} selected runs encountered a technical error.",
            },
            evaluation_coverage=coverage,
            consolidated_metrics=metrics,
            scenario_results=scenarios,
            critical_failures=failures,
            recommendations=recommendations,
            historical_comparison=_historical_comparison(reports),
            individual_reports=references,
        )


def _metrics(reports: list[dict[str, Any]]) -> list[ConsolidatedMetric]:
    states: dict[str, dict[str, Any]] = {
        name: {"scores": [], "pass": 0, "fail": 0, "not_evaluated": 0, "error": 0, "missing": 0}
        for name in METRIC_NAMES
    }
    for report in reports:
        if _outcome(report) == "error":
            for name in METRIC_NAMES:
                states[name]["missing"] += 1
            continue
        by_name: dict[str, dict[str, Any]] = {}
        for raw in report.get("metrics") or []:
            if not isinstance(raw, dict):
                continue
            name = _canonical_metric(raw.get("name"))
            if name:
                by_name[name] = raw
        for name in METRIC_NAMES:
            metric = by_name.get(name)
            bucket = states[name]
            if metric is None:
                bucket["missing"] += 1
                continue
            state = str(metric.get("evaluation_status") or metric.get("status") or "").strip().lower().replace(" ", "_")
            if state in {"not_evaluated", "skipped", "insufficient_evidence", "unverified"}:
                bucket["not_evaluated"] += 1
                continue
            if state in {"error", "technical_error"}:
                bucket["error"] += 1
                continue
            score = _number(metric.get("score"))
            if score is None:
                bucket["missing"] += 1
                continue
            bucket["scores"].append(score)
            passed = metric.get("passed")
            if passed is True:
                bucket["pass"] += 1
            elif passed is False:
                bucket["fail"] += 1
    return [
        ConsolidatedMetric(
            name=name,
            average_score=_average(bucket["scores"]),
            evaluated_count=len(bucket["scores"]),
            pass_count=bucket["pass"],
            fail_count=bucket["fail"],
            not_evaluated_count=bucket["not_evaluated"],
            error_count=bucket["error"],
            missing_count=bucket["missing"],
            total_runs=len(reports),
            coverage=f"{len(bucket['scores'])} / {len(reports)}",
        )
        for name, bucket in states.items()
    ]


def _scenario_results(reports: list[dict[str, Any]]) -> list[ScenarioResult]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        grouped[str(report.get("scenario_id") or "Unknown")].append(report)
    results = []
    for scenario_id, items in sorted(grouped.items()):
        valid = [item for item in items if _outcome(item) in {"pass", "fail"} and _score(item) is not None]
        latest_valid = valid[0] if valid else None
        times = [value for value in (_timestamp(item) for item in items) if value]
        evaluation_id = str(latest_valid.get("evaluation_id") or "") if latest_valid else None
        results.append(ScenarioResult(
            scenario_id=scenario_id,
            total_runs=len(items),
            valid_runs=len(valid),
            technical_errors=sum(_outcome(item) == "error" for item in items),
            last_evaluated=max(times).isoformat() if times else None,
            latest_valid_evaluation_id=evaluation_id or None,
            latest_valid_score=_score(latest_valid) if latest_valid else None,
            latest_valid_outcome=_outcome(latest_valid) if latest_valid else None,
            report_url=f"/evaluations/{evaluation_id}/report" if evaluation_id else None,
        ))
    return results


def _issues(reports: list[dict[str, Any]]) -> list[ConsolidatedIssue]:
    issues: list[ConsolidatedIssue] = []
    for report in reports:
        evaluation_id = str(report.get("evaluation_id") or "")
        scenario_id = str(report.get("scenario_id") or "Unknown")
        url = f"/evaluations/{evaluation_id}/report"
        if _outcome(report) == "error":
            evidence = _safe_text(report.get("error") or report.get("message") or "A technical evaluation error was persisted.")
            issues.append(ConsolidatedIssue(
                category="Technical Error", severity="High", scenario_id=scenario_id,
                evaluation_id=evaluation_id, evidence=evidence, report_url=url, technical=True,
            ))
            continue
        analyses = report.get("failure_analysis") or []
        if isinstance(analyses, list):
            for failure in analyses:
                if not isinstance(failure, dict):
                    continue
                metric = _canonical_metric(failure.get("metric_name")) or _safe_text(failure.get("metric_name"))
                evidence = _safe_text(failure.get("reason") or failure.get("root_cause") or failure.get("actual") or "Persisted failure evidence is available in the individual report.")
                issues.append(ConsolidatedIssue(
                    category=_safe_text(failure.get("category") or "Agent Quality"),
                    severity=_safe_text(failure.get("severity")) or None,
                    metric=metric or None,
                    scenario_id=scenario_id,
                    evaluation_id=evaluation_id,
                    evidence=evidence,
                    report_url=url,
                ))
        if _outcome(report) == "fail" and not analyses:
            failed = [metric for metric in report.get("metrics") or [] if isinstance(metric, dict) and metric.get("passed") is False]
            for metric in failed:
                name = _canonical_metric(metric.get("name")) or _safe_text(metric.get("name"))
                evidence = _safe_text(metric.get("reason") or f"{name} failed in the persisted evaluation result.")
                issues.append(ConsolidatedIssue(
                    category="Metric Failure", metric=name or None, scenario_id=scenario_id,
                    evaluation_id=evaluation_id, evidence=evidence, report_url=url,
                ))
    return issues


def _recommendations(
    issues: list[ConsolidatedIssue], metrics: list[ConsolidatedMetric], reports: list[dict[str, Any]]
) -> list[ConsolidatedRecommendation]:
    recommendations: list[ConsolidatedRecommendation] = []
    grouped: dict[str, list[ConsolidatedIssue]] = defaultdict(list)
    for issue in issues:
        if not issue.technical and issue.metric in _RECOMMENDATIONS:
            grouped[str(issue.metric)].append(issue)
    for metric in METRIC_NAMES:
        related = grouped.get(metric, [])
        if not related:
            continue
        recommendations.append(ConsolidatedRecommendation(
            priority="High" if len(related) > 1 else "Medium",
            recommendation=_RECOMMENDATIONS[metric],
            trigger=f"{len(related)} persisted {metric} failure(s)",
            affected_scenarios=sorted({item.scenario_id for item in related if item.scenario_id}),
            evaluation_ids=sorted({item.evaluation_id for item in related if item.evaluation_id}),
        ))
    technical = [issue for issue in issues if issue.technical]
    if technical:
        recommendations.append(ConsolidatedRecommendation(
            priority="High" if len(technical) / max(len(reports), 1) >= 0.25 else "Medium",
            recommendation="Investigate integration and execution reliability separately from agent quality.",
            trigger=f"{len(technical)} technical-error run(s)",
            affected_scenarios=sorted({item.scenario_id for item in technical if item.scenario_id}),
            evaluation_ids=sorted({item.evaluation_id for item in technical if item.evaluation_id}),
        ))
    return recommendations


def _coverage(reports, scenarios, metrics, timestamps, warnings):
    counts = Counter(_outcome(report) for report in reports)
    scenario_coverage = [ScenarioCoverage(
        scenario_id=item.scenario_id,
        total_runs=item.total_runs,
        valid_runs=item.valid_runs,
        technical_errors=item.technical_errors,
        last_evaluated=item.last_evaluated,
    ).model_dump() for item in scenarios]
    return {
        "unique_scenarios_tested": len(scenarios),
        "total_evaluation_runs": len(reports),
        "valid_scored_runs": counts["pass"] + counts["fail"],
        "technical_error_runs": counts["error"],
        "unknown_outcome_runs": counts["unknown"],
        "evaluation_period": _period(timestamps),
        "outcome_distribution": {key: counts[key] for key in ("pass", "fail", "error", "unknown")},
        "scenario_coverage": scenario_coverage,
        "metric_coverage": [metric.model_dump() for metric in metrics],
        "comparability_warnings": list(warnings),
    }


def _reference(report: dict[str, Any]) -> ConsolidatedEvaluationReference:
    evaluation_id = str(report.get("evaluation_id") or "")
    outcome = _outcome(report)
    timestamp = _timestamp(report)
    return ConsolidatedEvaluationReference(
        scenario_id=str(report.get("scenario_id") or "Unknown"),
        evaluation_id=evaluation_id,
        timestamp=timestamp.isoformat() if timestamp else None,
        outcome=outcome,
        score=_score(report),
        technical_status="ERROR" if outcome == "error" else "No technical error recorded",
        report_url=f"/evaluations/{evaluation_id}/report",
    )


def _canonical_metric(value: Any) -> str | None:
    text = str(value or "").strip()
    lowered = text.lower()
    if lowered in _METRIC_ALIASES:
        return _METRIC_ALIASES[lowered]
    return next((name for name in METRIC_NAMES if name.lower() == lowered), None)


def _history_reasons(reports: list[dict[str, Any]]) -> list[str]:
    reasons = []
    if len(reports) < 2:
        reasons.append("Only one qualifying evaluation run is available.")
    if not reports or any(not report.get("evaluation_config_hash") for report in reports):
        reasons.append("Evaluator configuration provenance is unavailable for one or more runs.")
    if not reports or any(not report.get("scenario_version") and not report.get("scenario_hash") for report in reports):
        reasons.append("Scenario version provenance is unavailable for one or more runs.")
    return reasons or ["No comparable period or batch identifiers are persisted."]


def _historical_comparison(reports: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        batch = report.get("evaluation_batch_id") or report.get("batch_id") or report.get("evaluation_period")
        if batch:
            grouped[str(batch)].append(report)
    if len(grouped) < 2:
        return {"status": "insufficient", "message": "Insufficient comparable evaluation history", "reasons": _history_reasons(reports)}
    ordered = sorted(grouped.items(), key=lambda pair: max((_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc)) for item in pair[1]))
    (previous_id, previous), (current_id, current) = ordered[-2:]
    previous_config = {item.get("evaluation_config_hash") for item in previous}
    current_config = {item.get("evaluation_config_hash") for item in current}
    previous_scenarios = {str(item.get("scenario_id")) for item in previous}
    current_scenarios = {str(item.get("scenario_id")) for item in current}
    previous_metrics = {_canonical_metric(metric.get("name")) for item in previous for metric in item.get("metrics") or [] if isinstance(metric, dict)}
    current_metrics = {_canonical_metric(metric.get("name")) for item in current for metric in item.get("metrics") or [] if isinstance(metric, dict)}
    if None in previous_config | current_config or previous_config != current_config or previous_scenarios != current_scenarios or previous_metrics != current_metrics:
        return {
            "status": "insufficient",
            "message": "Insufficient comparable evaluation history",
            "reasons": ["The two latest persisted batches have incompatible configuration, scenario, or metric provenance."],
        }
    previous_scores = [_score(item) for item in previous if _outcome(item) in {"pass", "fail"} and _score(item) is not None]
    current_scores = [_score(item) for item in current if _outcome(item) in {"pass", "fail"} and _score(item) is not None]
    previous_mean, current_mean = _average(previous_scores), _average(current_scores)
    previous_counts, current_counts = Counter(_outcome(item) for item in previous), Counter(_outcome(item) for item in current)
    previous_metric_map = {item.name: item.average_score for item in _metrics(previous)}
    current_metric_map = {item.name: item.average_score for item in _metrics(current)}
    metric_changes = [
        {"metric": name, "previous": previous_metric_map[name], "current": current_metric_map[name], "change": round(current_metric_map[name] - previous_metric_map[name], 4)}
        for name in METRIC_NAMES if previous_metric_map[name] is not None and current_metric_map[name] is not None
    ]
    return {
        "status": "comparable",
        "message": "Comparable evaluation history available",
        "previous_batch": previous_id,
        "current_batch": current_id,
        "previous_mean_score": previous_mean,
        "current_mean_score": current_mean,
        "mean_score_change": round(current_mean - previous_mean, 4) if previous_mean is not None and current_mean is not None else None,
        "pass_change": current_counts["pass"] - previous_counts["pass"],
        "fail_change": current_counts["fail"] - previous_counts["fail"],
        "metric_changes": metric_changes,
        "reasons": [],
    }


def _performance_summary(name, scenarios, runs, counts, mean):
    score = f"{round(mean * 100)}%" if mean is not None else "unavailable"
    return (
        f"{name} was evaluated across {scenarios} unique scenario(s) in {runs} evaluation run(s). "
        f"{counts['pass']} run(s) passed, {counts['fail']} failed, {counts['error']} encountered a technical error, "
        f"and {counts['unknown']} had an unknown outcome. The mean selected-run score was {score}."
    )


def _period(values: list[datetime]) -> dict[str, str | None]:
    return {"from": min(values).isoformat() if values else None, "to": max(values).isoformat() if values else None}


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        safe = [f"{key}: {_safe_text(item)}" for key, item in value.items() if not _SENSITIVE_KEY.search(str(key)) and isinstance(item, (str, int, float, bool))]
        value = "; ".join(safe)
    elif isinstance(value, list):
        value = "; ".join(_safe_text(item) for item in value[:5])
    text = re.sub(
        r"(?i)\b(token|password|secret|api[_-]?key|authorization)\b\s*[:=]\s*(?:(?:bearer|basic)\s+)?[^\s;,]+",
        r"\1: [REDACTED]",
        str(value),
    )
    return text[:1200]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None
