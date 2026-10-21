"""HTTP API for persisted evaluation reports."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from app.log_stream import log_manager
from app.interaction_protocol import interaction_manager

from app.evaluation_store import get_evaluation_report, list_evaluation_reports
from app.report_engine import (
    build_enterprise_report,
    build_enterprise_report_docx,
    build_enterprise_report_html,
    build_enterprise_report_pdf,
    build_executive_report,
    build_executive_report_docx,
    build_executive_report_html,
    build_executive_report_pdf,
    build_technical_report,
    build_technical_report_docx,
    build_technical_report_html,
    build_technical_report_pdf,
)

router = APIRouter(prefix="/evaluations", tags=["Evaluations"])


@router.get("")
def list_evaluations(connection_id: Optional[str] = None) -> list[dict[str, Any]]:
    return [_summary(report) for report in list_evaluation_reports(connection_id=connection_id)]


@router.get("/{evaluation_id}")
def get_evaluation(evaluation_id: str) -> dict[str, Any]:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return report


@router.get("/{evaluation_id}/report")
def get_evaluation_report_view(evaluation_id: str) -> dict[str, Any]:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return build_enterprise_report(report)


@router.get("/{evaluation_id}/report/executive")
def get_evaluation_executive_report_view(evaluation_id: str) -> dict[str, Any]:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return build_executive_report(report)


@router.get("/{evaluation_id}/report/technical")
def get_evaluation_technical_report_view(evaluation_id: str) -> dict[str, Any]:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return build_technical_report(report)


@router.get("/{evaluation_id}/report/json")
def download_evaluation_report_json(evaluation_id: str) -> JSONResponse:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    filename = f"evalforge-report-{evaluation_id}.json"
    return JSONResponse(
        content=build_enterprise_report(report),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{evaluation_id}/report/html")
def download_evaluation_report_html(evaluation_id: str) -> HTMLResponse:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    filename = f"evalforge-report-{evaluation_id}.html"
    return HTMLResponse(
        content=build_enterprise_report_html(report),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{evaluation_id}/report/pdf")
def download_evaluation_report_pdf(evaluation_id: str) -> Response:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    filename = f"evalforge-report-{evaluation_id}.pdf"
    return Response(
        content=build_enterprise_report_pdf(report),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{evaluation_id}/report/docx")
def download_evaluation_report_docx(evaluation_id: str) -> Response:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    filename = f"evalforge-report-{evaluation_id}.docx"
    return Response(
        content=build_enterprise_report_docx(report),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{evaluation_id}/report/executive/json")
def download_evaluation_executive_report_json(evaluation_id: str) -> JSONResponse:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    filename = f"evalforge-executive-report-{evaluation_id}.json"
    return JSONResponse(
        content=build_executive_report(report),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{evaluation_id}/report/executive/html")
def download_evaluation_executive_report_html(evaluation_id: str) -> HTMLResponse:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    filename = f"evalforge-executive-report-{evaluation_id}.html"
    return HTMLResponse(
        content=build_executive_report_html(report),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{evaluation_id}/report/executive/pdf")
def download_evaluation_executive_report_pdf(evaluation_id: str) -> Response:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    filename = f"evalforge-executive-report-{evaluation_id}.pdf"
    return Response(
        content=build_executive_report_pdf(report),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{evaluation_id}/report/executive/docx")
def download_evaluation_executive_report_docx(evaluation_id: str) -> Response:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    filename = f"evalforge-executive-report-{evaluation_id}.docx"
    return Response(
        content=build_executive_report_docx(report),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{evaluation_id}/report/technical/json")
def download_evaluation_technical_report_json(evaluation_id: str) -> JSONResponse:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    filename = f"evalforge-technical-report-{evaluation_id}.json"
    return JSONResponse(
        content=build_technical_report(report),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{evaluation_id}/report/technical/html")
def download_evaluation_technical_report_html(evaluation_id: str) -> HTMLResponse:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    filename = f"evalforge-technical-report-{evaluation_id}.html"
    return HTMLResponse(
        content=build_technical_report_html(report),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{evaluation_id}/report/technical/pdf")
def download_evaluation_technical_report_pdf(evaluation_id: str) -> Response:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    filename = f"evalforge-technical-report-{evaluation_id}.pdf"
    return Response(
        content=build_technical_report_pdf(report),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{evaluation_id}/report/technical/docx")
def download_evaluation_technical_report_docx(evaluation_id: str) -> Response:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    filename = f"evalforge-technical-report-{evaluation_id}.docx"
    return Response(
        content=build_technical_report_docx(report),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{evaluation_id}/transcript")
def get_evaluation_transcript(evaluation_id: str) -> dict[str, Any]:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return {
        "evaluation_id": evaluation_id,
        "transcript": report.get("transcript") or report.get("conversation") or [],
    }


@router.get("/{evaluation_id}/recordings")
def get_evaluation_recordings(evaluation_id: str) -> dict[str, Any]:
    report = get_evaluation_report(evaluation_id)
    if not report:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return {
        "evaluation_id": evaluation_id,
        "recording_metadata": report.get("recording_metadata") or [],
        "conversation_audio": report.get("conversation_audio") or {},
        "recording_status": report.get("recording_status") or "unavailable",
    }


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "evaluation_id": report.get("evaluation_id"),
        "connection_id": report.get("connection_id") or report.get("agent_id"),
        "agent_id": report.get("agent_id") or report.get("connection_id"),
        "agent_type": report.get("agent_type"),
        "provider": report.get("provider"),
        "adapter": report.get("adapter") or report.get("provider"),
        "scenario_id": report.get("scenario_id"),
        "session_id": report.get("session_id"),
        "provider_call_id": report.get("provider_call_id"),
        "status": report.get("status"),
        "overall_score": report.get("overall_score"),
        "passed": report.get("passed"),
        "success": report.get("success"),
        "created_at": report.get("created_at"),
        "started_at": report.get("started_at"),
        "ended_at": report.get("ended_at"),
        "duration_seconds": report.get("duration_seconds"),
        "recording_status": report.get("recording_status"),
    }

@router.websocket("/{evaluation_id}/logs/stream")
async def stream_evaluation_logs(websocket: WebSocket, evaluation_id: str):
    await websocket.accept()
    for log in log_manager.get_logs(evaluation_id):
        await websocket.send_json(log)
        
    queue = log_manager.subscribe(evaluation_id)
    try:
        while True:
            log = await queue.get()
            await websocket.send_json(log)
    except WebSocketDisconnect:
        pass
    finally:
        log_manager.unsubscribe(evaluation_id, queue)


@router.websocket("/{evaluation_id}/interactions/stream")
async def stream_evaluation_interactions(websocket: WebSocket, evaluation_id: str):
    await websocket.accept()
    queue = interaction_manager.subscribe(evaluation_id)
    try:
        while True:
            receive_task = asyncio.create_task(websocket.receive_json())
            send_task = asyncio.create_task(queue.get())
            done, pending = await asyncio.wait(
                {receive_task, send_task},
                timeout=20,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                for task in pending:
                    task.cancel()
                await websocket.send_json({"type": "heartbeat", "evaluation_id": evaluation_id})
                continue
            for task in pending:
                task.cancel()

            if receive_task in done:
                payload = receive_task.result()
                if isinstance(payload, dict) and payload.get("type") == "interaction_response":
                    interaction_id = str(payload.get("interaction_id") or "")
                    response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
                    interaction_manager.respond(interaction_id, response, evaluation_id=evaluation_id)

            if send_task in done:
                await websocket.send_json(send_task.result())
    except WebSocketDisconnect:
        pass
    finally:
        interaction_manager.unsubscribe(evaluation_id, queue)
        
@router.get("/{evaluation_id}/logs/download")
def download_evaluation_logs(evaluation_id: str):
    logs = log_manager.get_logs(evaluation_id)
    if not logs:
        try:
            report = get_evaluation_report(evaluation_id)
        except Exception:
            # Preserve the existing download path if the optional lookup fails.
            report = None
        if report and report.get("agent_type") == "calling":
            raise HTTPException(
                status_code=404,
                detail=(
                    "No calling diagnostic trace is available in this backend process. "
                    "Capture may have been disabled, or in-memory logs may have been lost "
                    "after a backend restart. Enable CALLING_DIAGNOSTICS_ENABLED before "
                    "a new evaluation and download its logs before restarting."
                ),
            )
    content = "\n".join([f"[{l['timestamp']}] {l['level']} - {l['message']}" for l in logs])
    return PlainTextResponse(content)
