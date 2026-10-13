"""SQL backend validator."""

from __future__ import annotations

import re
import time
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.backend_validation.assertions import AssertionEngine, assertion_engine
from app.backend_validation.models import BackendValidationCheck, BackendValidationSummary
from app.backend_validation.validators.base import BackendValidator


class SqlValidator(BackendValidator):
    def __init__(self, config: dict[str, Any], assertions: AssertionEngine | None = None) -> None:
        super().__init__(config)
        self.assertions = assertions or assertion_engine

    def validate(self, *, transcript: list[Any], scenario: Any) -> BackendValidationSummary:
        name = str(self.config.get("name") or "SQL backend validation")
        connection_config = self.config.get("connection") or {}
        connection_string = connection_config.get("connection_string")
        query = self.config.get("query")
        if not connection_string or not query:
            return BackendValidationSummary(
                status="SKIPPED",
                passed=None,
                reason="SQL backend validation skipped because connection_string or query was not configured.",
            )

        context = self._template_context(transcript=transcript, scenario=scenario)
        rendered_connection = self._render_template(str(connection_string), context)
        rendered_query = self._render_template(str(query), context)
        rendered_expect = self._render_value(self.config.get("expect") or {}, context)
        driver = str(connection_config.get("driver") or "sql").lower()

        started = time.perf_counter()
        try:
            engine = create_engine(rendered_connection)
            with engine.connect() as connection:
                rows = [dict(row._mapping) for row in connection.execute(text(rendered_query))]
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
        except SQLAlchemyError as exc:
            return BackendValidationSummary(
                status="ERROR",
                passed=False,
                reason=f"SQL backend validation failed: {exc.__class__.__name__}.",
                checks=[
                    BackendValidationCheck(
                        name=name,
                        passed=False,
                        reason=str(exc),
                        expected="SQL query result",
                        actual=exc.__class__.__name__,
                        evidence={
                            "driver": driver,
                            "query": rendered_query,
                            "extracted_variables": self.config.get("extracted_variables") or {},
                            "backend_connection": self.config.get("backend_connection_used") or {},
                        },
                    )
                ],
            )

        result_data: Any = rows[0] if len(rows) == 1 else rows
        evidence = {
            "driver": driver,
            "query": rendered_query,
            "row_count": len(rows),
            "response_time_ms": latency_ms,
            "extracted_variables": self.config.get("extracted_variables") or {},
            "backend_connection": self.config.get("backend_connection_used") or {},
        }
        checks = [
            BackendValidationCheck(
                name=f"{name}: query executed",
                passed=True,
                reason=f"SQL query returned {len(rows)} row(s).",
                expected="query success",
                actual=f"{len(rows)} row(s)",
                evidence=evidence,
            )
        ]
        checks.extend(self._assertion_checks(name, rendered_expect, result_data, evidence))

        passed = all(check.passed for check in checks)
        return BackendValidationSummary(
            status="PASS" if passed else "FAIL",
            passed=passed,
            reason="SQL backend validation passed." if passed else "SQL backend validation failed.",
            checks=checks,
        )

    def _assertion_checks(
        self,
        name: str,
        expect_config: Any,
        result_data: Any,
        evidence: dict[str, Any],
    ) -> list[BackendValidationCheck]:
        checks: list[BackendValidationCheck] = []
        for assertion in self.assertions.evaluate(result_data, expect_config):
            check_evidence = dict(evidence)
            check_evidence["assertion"] = assertion.model_dump()
            checks.append(
                BackendValidationCheck(
                    name=f"{name}: {assertion.jsonpath} {assertion.operator}",
                    passed=assertion.passed is True,
                    reason=assertion.message,
                    expected=assertion.expected,
                    actual=assertion.actual,
                    evidence=check_evidence,
                )
            )
        return checks

    def _template_context(self, *, transcript: list[Any], scenario: Any) -> dict[str, Any]:
        context: dict[str, Any] = {}
        agent = getattr(scenario, "agent", None)
        agent_config = getattr(agent, "config", None)
        if isinstance(agent_config, dict):
            context.update(agent_config)
        variables = self.config.get("variables")
        if isinstance(variables, dict):
            context.update(variables)
        context["scenario_id"] = getattr(scenario, "scenario_id", None)
        context["transcript"] = transcript
        return context

    def _render_value(self, value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return self._render_template(value, context)
        if isinstance(value, list):
            return [self._render_value(item, context) for item in value]
        if isinstance(value, dict):
            return {key: self._render_value(item, context) for key, item in value.items()}
        return value

    def _render_template(self, value: str, context: dict[str, Any]) -> str:
        def replace(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            replacement = self._json_path(context, key)
            return "" if replacement is None else str(replacement)

        return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", replace, value)

    def _json_path(self, data: Any, path: str) -> Any:
        current = data
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                index = int(part)
                current = current[index] if index < len(current) else None
            else:
                return None
        return current
