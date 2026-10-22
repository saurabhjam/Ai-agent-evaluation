"""In-memory distribution package for consolidated management reports."""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.evaluation_store import get_evaluation_report
from app.management.consolidated_exporters import render_consolidated_pdf
from app.management.consolidated_models import ConsolidatedReport
from app.report_engine import build_enterprise_report_pdf


_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class ConsolidatedPackageError(RuntimeError):
    """Raised when a complete report package cannot be generated atomically."""


@dataclass(frozen=True)
class ConsolidatedPackage:
    content: bytes
    filename: str


def build_consolidated_report_package(
    report: ConsolidatedReport,
    *,
    report_loader: Callable[[str], dict[str, Any] | None] = get_evaluation_report,
    individual_pdf_renderer: Callable[[dict[str, Any]], bytes] = build_enterprise_report_pdf,
    consolidated_pdf_renderer: Callable[[ConsolidatedReport], bytes] = render_consolidated_pdf,
) -> ConsolidatedPackage:
    """Build one complete ZIP or raise without returning a partial archive."""
    paths = {
        item.evaluation_id: _individual_report_path(item.scenario_id, item.evaluation_id)
        for item in report.individual_reports
    }
    rendered_reports: list[tuple[str, bytes]] = []
    for item in report.individual_reports:
        payload = report_loader(item.evaluation_id)
        if payload is None:
            raise ConsolidatedPackageError(
                f"Evaluation report {item.evaluation_id!r} is unavailable"
            )
        try:
            pdf = individual_pdf_renderer(payload)
        except Exception as exc:
            raise ConsolidatedPackageError(
                f"Could not generate individual report {item.evaluation_id!r}"
            ) from exc
        if not pdf:
            raise ConsolidatedPackageError(
                f"Individual report {item.evaluation_id!r} was empty"
            )
        rendered_reports.append((paths[item.evaluation_id], pdf))

    package_report = _with_bundled_references(report, paths)
    try:
        consolidated_pdf = consolidated_pdf_renderer(package_report)
    except Exception as exc:
        raise ConsolidatedPackageError("Could not generate consolidated report") from exc

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Consolidated-Evaluation-Report.pdf", consolidated_pdf)
        archive.writestr("README.txt", _readme(package_report, paths))
        for path, pdf in rendered_reports:
            archive.writestr(path, pdf)

    return ConsolidatedPackage(
        content=output.getvalue(),
        filename=f"{_safe_filename(report.agent_name, fallback='Agent')}-Evaluation-Report.zip",
    )


def _with_bundled_references(
    report: ConsolidatedReport, paths: dict[str, str]
) -> ConsolidatedReport:
    package_report = report.model_copy(deep=True)
    for item in package_report.individual_reports:
        item.report_url = paths[item.evaluation_id]
    for item in package_report.scenario_results:
        if item.latest_valid_evaluation_id in paths:
            item.report_url = paths[item.latest_valid_evaluation_id]
    for item in package_report.critical_failures:
        if item.evaluation_id in paths:
            item.report_url = paths[item.evaluation_id]
    return package_report


def _individual_report_path(scenario_id: str, evaluation_id: str) -> str:
    scenario = _safe_filename(scenario_id, fallback="scenario", max_length=80)
    evaluation = _safe_filename(evaluation_id, fallback="evaluation", max_length=128)
    return f"Individual-Reports/{scenario}_{evaluation}.pdf"


def _safe_filename(value: str, *, fallback: str, max_length: int = 100) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    safe = _UNSAFE_FILENAME.sub("-", ascii_value).strip(".-_")
    return (safe or fallback)[:max_length].rstrip(".-_") or fallback


def _readme(report: ConsolidatedReport, paths: dict[str, str]) -> str:
    lines = [
        "EvalForge Consolidated Evaluation Report Package",
        "",
        f"Agent: {report.agent_name}",
        f"Agent Type: {report.agent_type}",
        f"Generated At: {report.generated_at}",
        f"Included Evaluations: {len(report.individual_reports)}",
        "",
        "Contents:",
        "- Consolidated-Evaluation-Report.pdf: consolidated management report.",
        "- Individual-Reports/: one enterprise PDF for each included evaluation.",
        "",
        "Included individual reports:",
    ]
    lines.extend(
        f"- {item.evaluation_id}: {paths[item.evaluation_id]}"
        for item in report.individual_reports
    )
    return "\n".join(lines) + "\n"
