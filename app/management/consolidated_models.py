"""Public models for deterministic consolidated management reports."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ReportSelection(BaseModel):
    scenario_id: str | None = None
    status: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    included_evaluation_ids: list[str] = Field(default_factory=list)


class ConsolidatedMetric(BaseModel):
    name: str
    average_score: float | None = None
    evaluated_count: int = 0
    pass_count: int = 0
    fail_count: int = 0
    not_evaluated_count: int = 0
    error_count: int = 0
    missing_count: int = 0
    total_runs: int = 0
    coverage: str


class ScenarioCoverage(BaseModel):
    scenario_id: str
    total_runs: int
    valid_runs: int
    technical_errors: int
    last_evaluated: str | None = None


class ScenarioResult(ScenarioCoverage):
    latest_valid_evaluation_id: str | None = None
    latest_valid_score: float | None = None
    latest_valid_outcome: Literal["pass", "fail"] | None = None
    report_url: str | None = None


class ConsolidatedIssue(BaseModel):
    category: str
    severity: str | None = None
    metric: str | None = None
    scenario_id: str | None = None
    evaluation_id: str
    evidence: str
    report_url: str
    technical: bool = False


class ConsolidatedRecommendation(BaseModel):
    priority: Literal["High", "Medium", "Low"]
    recommendation: str
    trigger: str
    affected_scenarios: list[str] = Field(default_factory=list)
    evaluation_ids: list[str] = Field(default_factory=list)


class ConsolidatedEvaluationReference(BaseModel):
    scenario_id: str
    evaluation_id: str
    timestamp: str | None = None
    outcome: Literal["pass", "fail", "error", "unknown"]
    score: float | None = None
    technical_status: str
    report_url: str


class ConsolidatedReport(BaseModel):
    report_type: str = "EvalForge Consolidated Evaluation Report"
    generated_at: str
    agent_key: str
    agent_name: str
    agent_type: str
    provider: str | None = None
    adapter: str | None = None
    selection: ReportSelection
    section_order: list[str]
    executive_summary: dict[str, Any]
    evaluation_coverage: dict[str, Any]
    consolidated_metrics: list[ConsolidatedMetric]
    scenario_results: list[ScenarioResult]
    critical_failures: list[ConsolidatedIssue]
    recommendations: list[ConsolidatedRecommendation]
    historical_comparison: dict[str, Any]
    individual_reports: list[ConsolidatedEvaluationReference]
