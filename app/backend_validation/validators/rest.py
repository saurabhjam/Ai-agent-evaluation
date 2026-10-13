"""REST backend validator."""

from __future__ import annotations

import re
import time
from typing import Any

import requests

from app.backend_validation.assertions import AssertionEngine, assertion_engine
from app.backend_validation.models import BackendValidationCheck, BackendValidationSummary
from app.backend_validation.validators.base import BackendValidator


class RestValidator(BackendValidator):
    def __init__(self, config: dict[str, Any], assertions: AssertionEngine | None = None) -> None:
        super().__init__(config)
        self.assertions = assertions or assertion_engine

    def validate(self, *, transcript: list[Any], scenario: Any) -> BackendValidationSummary:
        if isinstance(self.config.get("request"), dict):
            return self._validate_rest_request(transcript=transcript, scenario=scenario)
        return self._validate_transcript_checks(transcript)

    def _validate_rest_request(self, *, transcript: list[Any], scenario: Any) -> BackendValidationSummary:
        name = str(self.config.get("name") or "REST backend validation")
        request_config = self.config.get("request") or {}
        expect_config = self.config.get("expect") or {}

        method = str(request_config.get("method") or "GET").upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            return BackendValidationSummary(
                status="ERROR",
                passed=False,
                reason=f"Unsupported REST validation method: {method}.",
                checks=[
                    BackendValidationCheck(
                        name=name,
                        passed=False,
                        reason=f"Unsupported method: {method}.",
                        expected="GET, POST, PUT, PATCH, DELETE",
                        actual=method,
                    )
                ],
            )

        context = self._template_context(transcript=transcript, scenario=scenario)
        url = self._render_template(request_config.get("url"), context)
        if not url:
            return BackendValidationSummary(
                status="SKIPPED",
                passed=None,
                reason="REST backend validation skipped because request.url was not configured.",
            )

        headers = self._render_mapping(request_config.get("headers"), context)
        params = self._render_mapping(request_config.get("query") or request_config.get("params"), context)
        body = self._render_value(request_config.get("json") or request_config.get("body"), context)
        timeout = float(request_config.get("timeout", self.config.get("timeout", 10)))
        verify = bool(request_config.get("verify_ssl", self.config.get("verify_ssl", True)))
        max_body_size = int(self.config.get("max_response_body_size", request_config.get("max_response_body_size", 4096)))
        auth = self._auth(request_config)

        bearer_token = request_config.get("bearer_token") or self.config.get("bearer_token")
        if bearer_token:
            headers["Authorization"] = f"Bearer {self._render_template(bearer_token, context)}"

        started = time.perf_counter()
        try:
            response = requests.request(
                method,
                url,
                headers=headers or None,
                params=params or None,
                json=body if body is not None else None,
                auth=auth,
                timeout=timeout,
                verify=verify,
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
        except requests.RequestException as exc:
            return BackendValidationSummary(
                status="ERROR",
                passed=False,
                reason=f"REST backend validation request failed: {exc.__class__.__name__}.",
                checks=[
                    BackendValidationCheck(
                        name=name,
                        passed=False,
                        reason=str(exc),
                        expected="HTTP response",
                        actual=exc.__class__.__name__,
                        evidence={"endpoint": url, "method": method},
                    )
                ],
            )

        response_text = response.text or ""
        response_body = response_text[:max_body_size]
        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("x-correlation-id")
            or response.headers.get("request-id")
        )
        evidence = {
            "endpoint": url,
            "method": method,
            "status_code": response.status_code,
            "response_time_ms": latency_ms,
            "response_body": response_body,
            "request_id": request_id,
            "extracted_variables": self.config.get("extracted_variables") or {},
            "backend_connection": self.config.get("backend_connection_used") or {},
        }

        try:
            response_json = response.json()
        except ValueError:
            response_json = None

        checks = [
            BackendValidationCheck(
                name=f"{name}: HTTP status",
                passed=200 <= response.status_code < 300,
                reason=f"HTTP status was {response.status_code}.",
                expected="2xx",
                actual=response.status_code,
                evidence=evidence,
            )
        ]
        checks.extend(self._expectation_checks(name, expect_config, response_json, evidence))

        passed = all(check.passed for check in checks)
        return BackendValidationSummary(
            status="PASS" if passed else "FAIL",
            passed=passed,
            reason="REST backend validation passed." if passed else "REST backend validation failed.",
            checks=checks,
        )

    def _expectation_checks(
        self,
        name: str,
        expect_config: Any,
        response_json: Any,
        evidence: dict[str, Any],
    ) -> list[BackendValidationCheck]:
        checks: list[BackendValidationCheck] = []
        if not isinstance(expect_config, dict):
            return checks
        for assertion in self.assertions.evaluate(response_json, expect_config):
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

    def _validate_transcript_checks(self, transcript: list[Any]) -> BackendValidationSummary:
        checks: list[BackendValidationCheck] = []
        text = self._transcript_text(transcript)

        for phrase in self._as_list(self.config.get("expected_phrases")):
            phrase_text = str(phrase)
            found = phrase_text.lower() in text
            checks.append(
                BackendValidationCheck(
                    name="Expected phrase",
                    passed=found,
                    reason="Expected phrase was found." if found else "Expected phrase was not found.",
                    expected=phrase_text,
                    actual="found" if found else "missing",
                )
            )

        for phrase in self._as_list(self.config.get("forbidden_phrases")):
            phrase_text = str(phrase)
            found = phrase_text.lower() in text
            checks.append(
                BackendValidationCheck(
                    name="Forbidden phrase",
                    passed=not found,
                    reason="Forbidden phrase was absent." if not found else "Forbidden phrase was present.",
                    expected=f"absent: {phrase_text}",
                    actual="present" if found else "absent",
                )
            )

        min_agent_turns = self.config.get("min_agent_turns")
        if min_agent_turns is not None:
            actual = self._count_role(transcript, {"agent", "assistant"})
            expected = int(min_agent_turns)
            checks.append(
                BackendValidationCheck(
                    name="Minimum agent turns",
                    passed=actual >= expected,
                    reason=f"Agent turns: {actual}; required: {expected}.",
                    expected=expected,
                    actual=actual,
                )
            )

        min_user_turns = self.config.get("min_user_turns")
        if min_user_turns is not None:
            actual = self._count_role(transcript, {"simulated_user", "user", "customer"})
            expected = int(min_user_turns)
            checks.append(
                BackendValidationCheck(
                    name="Minimum user turns",
                    passed=actual >= expected,
                    reason=f"User turns: {actual}; required: {expected}.",
                    expected=expected,
                    actual=actual,
                )
            )

        passed = all(check.passed for check in checks) if checks else None
        return BackendValidationSummary(
            status="validated" if checks else "not_configured",
            passed=passed,
            reason=(
                "Backend validation checks passed."
                if passed is True
                else "One or more backend validation checks failed."
                if passed is False
                else "Backend validation was configured but no supported checks were found."
            ),
            checks=checks,
        )

    def _auth(self, request_config: dict[str, Any]) -> Any:
        basic_auth = request_config.get("basic_auth") or self.config.get("basic_auth")
        if isinstance(basic_auth, dict):
            username = basic_auth.get("username")
            password = basic_auth.get("password")
            if username is not None and password is not None:
                return (str(username), str(password))
        return None

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

    def _render_mapping(self, value: Any, context: dict[str, Any]) -> dict[str, Any]:
        rendered = self._render_value(value, context)
        return rendered if isinstance(rendered, dict) else {}

    def _render_value(self, value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return self._render_template(value, context)
        if isinstance(value, list):
            return [self._render_value(item, context) for item in value]
        if isinstance(value, dict):
            return {key: self._render_value(item, context) for key, item in value.items()}
        return value

    def _render_template(self, value: Any, context: dict[str, Any]) -> Any:
        if not isinstance(value, str):
            return value

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

    def _transcript_text(self, transcript: list[Any]) -> str:
        parts = []
        for message in transcript or []:
            content = self._message_value(message, "content")
            if content not in (None, ""):
                parts.append(str(content))
        return "\n".join(parts).lower()

    def _count_role(self, transcript: list[Any], roles: set[str]) -> int:
        count = 0
        for message in transcript or []:
            role = str(self._message_value(message, "role") or "").lower()
            if role in roles:
                count += 1
        return count

    def _message_value(self, message: Any, key: str) -> Any:
        if isinstance(message, dict):
            return message.get(key)
        return getattr(message, key, None)

    def _as_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]
