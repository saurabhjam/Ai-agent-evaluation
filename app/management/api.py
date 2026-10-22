"""Read-only FastAPI endpoints for management reporting."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse

from app.management.consolidated_exporters import (
    render_consolidated_csv,
    render_consolidated_docx,
    render_consolidated_html,
    render_consolidated_pdf,
)
from app.management.consolidated_models import ConsolidatedReport
from app.management.consolidated_package import (
    ConsolidatedPackageError,
    build_consolidated_report_package,
)
from app.management.consolidated_report import ConsolidatedReportEngine
from app.management.models import AgentDetail, PaginatedAgents, PaginatedEvaluations, ScenarioSummary
from app.management.service import AgentNotFoundError, ManagementAggregationService


router = APIRouter(prefix="/management", tags=["Management"])


def get_management_service() -> ManagementAggregationService:
    return ManagementAggregationService()


def get_consolidated_report_engine(
    service: ManagementAggregationService = Depends(get_management_service),
) -> ConsolidatedReportEngine:
    return ConsolidatedReportEngine(service)


@router.get("/agents", response_model=PaginatedAgents)
def list_management_agents(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    agent_type: Literal["chatbot", "voice", "calling", "legacy"] | None = None,
    provider: str | None = None,
    query: str | None = None,
    service: ManagementAggregationService = Depends(get_management_service),
) -> PaginatedAgents:
    return service.list_agents(page=page, page_size=page_size, agent_type=agent_type, provider=provider, query=query)


@router.get("/agents/{agent_key}", response_model=AgentDetail)
def get_management_agent(
    agent_key: str,
    service: ManagementAggregationService = Depends(get_management_service),
) -> AgentDetail:
    try:
        return service.get_agent(agent_key)
    except (AgentNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc


@router.get("/agents/{agent_key}/evaluations", response_model=PaginatedEvaluations)
def list_management_evaluations(
    agent_key: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    scenario_id: str | None = None,
    status: Literal["pass", "fail", "error", "unknown"] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    service: ManagementAggregationService = Depends(get_management_service),
) -> PaginatedEvaluations:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must be before date_to")
    try:
        return service.list_evaluations(
            agent_key,
            page=page,
            page_size=page_size,
            scenario_id=scenario_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
        )
    except (AgentNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc


@router.get("/agents/{agent_key}/scenarios", response_model=list[ScenarioSummary])
def list_management_scenarios(
    agent_key: str,
    service: ManagementAggregationService = Depends(get_management_service),
) -> list[ScenarioSummary]:
    try:
        return service.list_scenarios(agent_key)
    except (AgentNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc


def _build_consolidated(
    agent_key: str,
    scenario_id: str | None,
    status: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    engine: ConsolidatedReportEngine,
) -> ConsolidatedReport:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must be before date_to")
    try:
        return engine.build(
            agent_key, scenario_id=scenario_id, status=status, date_from=date_from, date_to=date_to
        )
    except (AgentNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc


@router.get("/agents/{agent_key}/consolidated-report", response_model=ConsolidatedReport)
def get_consolidated_report(
    agent_key: str,
    scenario_id: str | None = None,
    status: Literal["pass", "fail", "error", "unknown"] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    engine: ConsolidatedReportEngine = Depends(get_consolidated_report_engine),
) -> ConsolidatedReport:
    return _build_consolidated(agent_key, scenario_id, status, date_from, date_to, engine)


@router.get("/agents/{agent_key}/consolidated-report/html", response_class=HTMLResponse)
def download_consolidated_html(
    agent_key: str,
    scenario_id: str | None = None,
    status: Literal["pass", "fail", "error", "unknown"] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    engine: ConsolidatedReportEngine = Depends(get_consolidated_report_engine),
) -> HTMLResponse:
    report = _build_consolidated(agent_key, scenario_id, status, date_from, date_to, engine)
    return HTMLResponse(render_consolidated_html(report), headers={"Content-Disposition": "attachment; filename=evalforge-consolidated-report.html"})


@router.get("/agents/{agent_key}/consolidated-report/pdf")
def download_consolidated_pdf(
    agent_key: str,
    scenario_id: str | None = None,
    status: Literal["pass", "fail", "error", "unknown"] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    engine: ConsolidatedReportEngine = Depends(get_consolidated_report_engine),
) -> Response:
    report = _build_consolidated(agent_key, scenario_id, status, date_from, date_to, engine)
    return Response(render_consolidated_pdf(report), media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=evalforge-consolidated-report.pdf"})


@router.get("/agents/{agent_key}/consolidated-report/docx")
def download_consolidated_docx(
    agent_key: str,
    scenario_id: str | None = None,
    status: Literal["pass", "fail", "error", "unknown"] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    engine: ConsolidatedReportEngine = Depends(get_consolidated_report_engine),
) -> Response:
    report = _build_consolidated(agent_key, scenario_id, status, date_from, date_to, engine)
    return Response(render_consolidated_docx(report), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": "attachment; filename=evalforge-consolidated-report.docx"})


@router.get("/agents/{agent_key}/consolidated-report/csv")
def download_consolidated_csv(
    agent_key: str,
    scenario_id: str | None = None,
    status: Literal["pass", "fail", "error", "unknown"] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    engine: ConsolidatedReportEngine = Depends(get_consolidated_report_engine),
) -> Response:
    report = _build_consolidated(agent_key, scenario_id, status, date_from, date_to, engine)
    return Response(render_consolidated_csv(report), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=evalforge-consolidated-report.csv"})


@router.get("/agents/{agent_key}/consolidated-report/package")
def download_consolidated_package(
    agent_key: str,
    scenario_id: str | None = None,
    status: Literal["pass", "fail", "error", "unknown"] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    engine: ConsolidatedReportEngine = Depends(get_consolidated_report_engine),
) -> Response:
    report = _build_consolidated(agent_key, scenario_id, status, date_from, date_to, engine)
    try:
        package = build_consolidated_report_package(report)
    except ConsolidatedPackageError as exc:
        raise HTTPException(
            status_code=500,
            detail="The complete consolidated report package could not be generated.",
        ) from exc
    return Response(
        package.content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{package.filename}"'},
    )
