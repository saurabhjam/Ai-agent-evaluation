"""Read-only aggregation over persisted evaluation report payloads."""

from __future__ import annotations

import math
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from app.config import settings
from app.evaluation_store import list_evaluation_reports
from app.management.identity import AgentIdentityResolver, evaluation_matches_agent, make_agent_key
from app.management.models import (
    AgentDetail,
    AgentSummary,
    EvaluationReference,
    MetricAverage,
    OutcomeCounts,
    PaginatedAgents,
    PaginatedEvaluations,
    ScenarioSummary,
)


class AgentNotFoundError(LookupError):
    pass


class ManagementAggregationService:
    """Aggregate existing reports without executing or mutating evaluations."""

    def __init__(
        self,
        report_loader: Callable[[], list[dict[str, Any]]] | None = None,
        identity_resolver: AgentIdentityResolver | None = None,
        baseline_at: datetime | None = None,
    ) -> None:
        self._report_loader = report_loader or list_evaluation_reports
        self._identity_resolver = identity_resolver or AgentIdentityResolver()
        self._baseline_at = _utc(baseline_at or settings.management_baseline_at)

    def list_agents(
        self,
        *,
        page: int = 1,
        page_size: int = 25,
        agent_type: str | None = None,
        provider: str | None = None,
        query: str | None = None,
    ) -> PaginatedAgents:
        reports = self._reports()
        identities = self._identity_resolver.resolve_all(reports)
        grouped = _group_reports(reports)
        # Connections are enrolled in management by their first post-baseline
        # evaluation. Existing connection records alone are not displayed.
        items = [self._summary(identities[key], grouped[key]) for key in grouped if key in identities]
        if agent_type:
            items = [item for item in items if item.agent_type == agent_type.lower()]
        if provider:
            items = [item for item in items if (item.provider or item.adapter or "").lower() == provider.lower()]
        if query:
            needle = query.lower()
            items = [item for item in items if needle in item.name.lower() or needle in item.connection_id.lower()]
        items.sort(key=lambda item: (item.latest_evaluation_at or "", item.name.lower()), reverse=True)
        page_items, total, pages = _paginate(items, page, page_size)
        return PaginatedAgents(items=page_items, page=page, page_size=page_size, total=total, pages=pages)

    def get_agent(self, agent_key: str) -> AgentDetail:
        reports = self._reports()
        identities = self._identity_resolver.resolve_all(reports)
        identity = identities.get(agent_key)
        if identity is None:
            raise AgentNotFoundError(agent_key)
        selected = [report for report in reports if evaluation_matches_agent(report, agent_key)]
        summary = self._summary(identity, selected)
        return AgentDetail(
            **summary.model_dump(),
            metric_averages=_metric_averages(selected),
            scenarios=_scenario_summaries(selected),
            evaluations=[_reference(report) for report in _sort_reports(selected)],
        )

    def list_evaluations(
        self,
        agent_key: str,
        *,
        page: int = 1,
        page_size: int = 25,
        scenario_id: str | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> PaginatedEvaluations:
        detail = self.get_agent(agent_key)
        reports = [report for report in self._reports() if evaluation_matches_agent(report, agent_key)]
        if scenario_id:
            reports = [report for report in reports if str(report.get("scenario_id") or "") == scenario_id]
        if status:
            reports = [report for report in reports if _outcome(report) == status.lower()]
        if date_from:
            reports = [report for report in reports if (_timestamp(report) and _timestamp(report) >= _utc(date_from))]
        if date_to:
            reports = [report for report in reports if (_timestamp(report) and _timestamp(report) <= _utc(date_to))]
        references = [_reference(report) for report in _sort_reports(reports)]
        items, total, pages = _paginate(references, page, page_size)
        return PaginatedEvaluations(
            agent_key=detail.agent_key, items=items, page=page, page_size=page_size, total=total, pages=pages
        )

    def list_scenarios(self, agent_key: str) -> list[ScenarioSummary]:
        self.get_agent(agent_key)
        reports = [report for report in self._reports() if evaluation_matches_agent(report, agent_key)]
        return _scenario_summaries(reports)

    def select_reports(
        self,
        agent_key: str,
        *,
        scenario_id: str | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return defensive copies of qualifying reports for read-only consumers."""
        self.get_agent(agent_key)
        reports = [report for report in self._reports() if evaluation_matches_agent(report, agent_key)]
        if scenario_id:
            reports = [report for report in reports if str(report.get("scenario_id") or "") == scenario_id]
        if status:
            reports = [report for report in reports if _outcome(report) == status.lower()]
        if date_from:
            reports = [report for report in reports if (_timestamp(report) and _timestamp(report) >= _utc(date_from))]
        if date_to:
            reports = [report for report in reports if (_timestamp(report) and _timestamp(report) <= _utc(date_to))]
        return _sort_reports(reports)

    def _reports(self) -> list[dict[str, Any]]:
        # Defensive copies guarantee the management layer cannot mutate loader-owned payloads.
        reports = deepcopy(self._report_loader())
        return [report for report in reports if _is_management_report(report, self._baseline_at)]

    def _summary(self, identity: Any, reports: list[dict[str, Any]]) -> AgentSummary:
        valid_scores = [_score(report) for report in reports if _is_valid_scored_run(report)]
        valid_scores = [score for score in valid_scores if score is not None]
        timestamps = [_timestamp(report) for report in reports]
        timestamps = [value for value in timestamps if value is not None]
        scenarios = {str(report.get("scenario_id")) for report in reports if report.get("scenario_id")}
        return AgentSummary(
            **identity.model_dump(exclude={"metadata"}),
            total_runs=len(reports),
            unique_scenarios=len(scenarios),
            outcome_counts=_outcome_counts(reports),
            latest_evaluation_at=max(timestamps).isoformat() if timestamps else None,
            overall_average_score=_average(valid_scores),
            comparability_warnings=_comparability_warnings(reports),
        )


def _group_reports(reports: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        connection_id = report.get("connection_id") or report.get("agent_id")
        if not connection_id:
            continue
        grouped[make_agent_key(_agent_type(report), str(connection_id))].append(report)
    return grouped


def _agent_type(report: dict[str, Any]) -> str:
    value = str(report.get("agent_type") or "").lower()
    if value in {"chatbot", "voice", "calling"}:
        return value
    return "calling" if str(report.get("provider") or "").lower() in {"vapi", "twilio", "retell", "bland", "sip"} else "legacy"


def _outcome(report: dict[str, Any]) -> str:
    status = str(report.get("status") or "").strip().lower()
    if report.get("success") is False or status in {"error", "failed", "failure"}:
        return "error"
    if report.get("passed") is True:
        return "pass"
    if report.get("passed") is False:
        return "fail"
    if status in {"pass", "passed", "success", "completed"}:
        return "pass" if status in {"pass", "passed", "success"} else "unknown"
    return "unknown"


def _outcome_counts(reports: Iterable[dict[str, Any]]) -> OutcomeCounts:
    values = OutcomeCounts()
    fields = {"pass": "passed", "fail": "failed", "error": "error", "unknown": "unknown"}
    for report in reports:
        field = fields[_outcome(report)]
        setattr(values, field, getattr(values, field) + 1)
    return values


def _is_valid_scored_run(report: dict[str, Any]) -> bool:
    return _outcome(report) in {"pass", "fail"} and _score(report) is not None


def _score(report: dict[str, Any]) -> float | None:
    value = report.get("overall_score")
    if isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if math.isfinite(score) else None


def _metric_averages(reports: list[dict[str, Any]]) -> list[MetricAverage]:
    scores: dict[str, list[float]] = defaultdict(list)
    skipped: dict[str, int] = defaultdict(int)
    names: set[str] = set()
    for report in reports:
        if _outcome(report) == "error":
            continue
        for metric in report.get("metrics") or []:
            if not isinstance(metric, dict) or not metric.get("name"):
                continue
            name = str(metric["name"])
            names.add(name)
            state = str(metric.get("evaluation_status") or "").lower()
            if state in {"not_evaluated", "error"}:
                skipped[name] += 1
                continue
            value = _numeric(metric.get("score"))
            if value is None:
                skipped[name] += 1
            else:
                scores[name].append(value)
    return [
        MetricAverage(name=name, average_score=_average(scores[name]) or 0.0, evaluated_runs=len(scores[name]), skipped_runs=skipped[name])
        for name in sorted(names)
        if scores[name]
    ]


def _scenario_summaries(reports: list[dict[str, Any]]) -> list[ScenarioSummary]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        grouped[str(report.get("scenario_id") or "unknown")].append(report)
    result: list[ScenarioSummary] = []
    for scenario_id, scenario_reports in grouped.items():
        ordered = _sort_reports(scenario_reports)
        valid = [report for report in ordered if _is_valid_scored_run(report)]
        scores = [_score(report) for report in valid]
        result.append(ScenarioSummary(
            scenario_id=scenario_id,
            total_runs=len(scenario_reports),
            latest_run=_reference(ordered[0]) if ordered else None,
            latest_valid_run=_reference(valid[0]) if valid else None,
            outcome_counts=_outcome_counts(scenario_reports),
            average_score=_average([value for value in scores if value is not None]),
        ))
    return sorted(result, key=lambda item: item.scenario_id)


def _reference(report: dict[str, Any]) -> EvaluationReference:
    evaluation_id = str(report.get("evaluation_id") or "")
    timestamp = _timestamp(report)
    return EvaluationReference(
        evaluation_id=evaluation_id,
        scenario_id=str(report.get("scenario_id")) if report.get("scenario_id") is not None else None,
        created_at=timestamp.isoformat() if timestamp else None,
        status=_outcome(report),
        overall_score=_score(report),
        passed=report.get("passed") if isinstance(report.get("passed"), bool) else None,
        report_url=f"/evaluations/{evaluation_id}/report" if evaluation_id else "",
    )


def _comparability_warnings(reports: list[dict[str, Any]]) -> list[str]:
    if len(reports) < 2:
        return []
    warnings: list[str] = []
    if any(not report.get("evaluation_config_hash") for report in reports):
        warnings.append("Historical evaluator configuration cannot be verified for every run.")
    if any(not report.get("scenario_version") and not report.get("scenario_hash") for report in reports):
        warnings.append("Historical scenario versions cannot be verified for every run.")
    metric_sets = {tuple(sorted(str(metric.get("name")) for metric in report.get("metrics") or [] if isinstance(metric, dict))) for report in reports}
    if len(metric_sets) > 1:
        warnings.append("Runs contain different metric sets; metric averages use only runs where each metric was evaluated.")
    return warnings


def _timestamp(report: dict[str, Any]) -> datetime | None:
    for key in ("created_at", "ended_at", "started_at"):
        value = report.get(key)
        if not value:
            continue
        try:
            return _utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
        except ValueError:
            continue
    return None


def _is_management_report(report: dict[str, Any], baseline_at: datetime) -> bool:
    """Fail closed when a report has no trustworthy creation timestamp."""
    value = report.get("created_at")
    if not value:
        return False
    try:
        created_at = _utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return False
    return created_at >= baseline_at


def _sort_reports(reports: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(reports, key=lambda report: _timestamp(report) or minimum, reverse=True)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _paginate(items: list[Any], page: int, page_size: int) -> tuple[list[Any], int, int]:
    total = len(items)
    pages = math.ceil(total / page_size) if total else 0
    start = (page - 1) * page_size
    return items[start:start + page_size], total, pages
