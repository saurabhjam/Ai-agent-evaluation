"""Public response models for the management API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class OutcomeCounts(BaseModel):
    passed: int = 0
    failed: int = 0
    error: int = 0
    unknown: int = 0


class MetricAverage(BaseModel):
    name: str
    average_score: float
    evaluated_runs: int
    skipped_runs: int = 0


class EvaluationReference(BaseModel):
    evaluation_id: str
    scenario_id: str | None = None
    created_at: str | None = None
    status: Literal["pass", "fail", "error", "unknown"]
    overall_score: float | None = None
    passed: bool | None = None
    report_url: str


class ScenarioSummary(BaseModel):
    scenario_id: str
    total_runs: int
    latest_run: EvaluationReference | None = None
    latest_valid_run: EvaluationReference | None = None
    outcome_counts: OutcomeCounts
    average_score: float | None = None


class AgentSummary(BaseModel):
    agent_key: str
    connection_id: str
    name: str
    agent_type: str
    adapter: str | None = None
    provider: str | None = None
    connection_status: Literal["available", "missing"]
    total_runs: int
    unique_scenarios: int
    outcome_counts: OutcomeCounts
    latest_evaluation_at: str | None = None
    overall_average_score: float | None = None
    comparability_warnings: list[str] = Field(default_factory=list)


class AgentDetail(AgentSummary):
    metric_averages: list[MetricAverage] = Field(default_factory=list)
    scenarios: list[ScenarioSummary] = Field(default_factory=list)
    evaluations: list[EvaluationReference] = Field(default_factory=list)


class PaginatedAgents(BaseModel):
    items: list[AgentSummary]
    page: int
    page_size: int
    total: int
    pages: int


class PaginatedEvaluations(BaseModel):
    agent_key: str
    items: list[EvaluationReference]
    page: int
    page_size: int
    total: int
    pages: int


class ManagementSecurityStatus(BaseModel):
    multi_tenant_ready: bool = False
    blockers: list[str] = Field(default_factory=list)


class AgentIdentity(BaseModel):
    agent_key: str
    connection_id: str
    name: str
    agent_type: str
    adapter: str | None = None
    provider: str | None = None
    connection_status: Literal["available", "missing"]
    metadata: dict[str, Any] = Field(default_factory=dict)
