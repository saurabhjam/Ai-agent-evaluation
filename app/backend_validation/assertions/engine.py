"""Generic assertion engine for backend validation providers."""

from __future__ import annotations

from typing import Any

from app.backend_validation.assertions.jsonpath import MISSING, resolve_jsonpath
from app.backend_validation.assertions.models import AssertionResult
from app.backend_validation.assertions.operators import evaluate_operator


OPERATORS = {
    "equals",
    "not_equals",
    "contains",
    "starts_with",
    "ends_with",
    "exists",
    "not_exists",
    "greater_than",
    "greater_than_or_equal",
    "less_than",
    "less_than_or_equal",
    "in",
    "not_in",
    "length",
    "regex",
}


class AssertionEngine:
    def evaluate(self, data: Any, expectations: Any) -> list[AssertionResult]:
        if not isinstance(expectations, dict):
            return []
        results: list[AssertionResult] = []
        for raw_path, raw_assertions in expectations.items():
            path = self._normalize_path(str(raw_path))
            try:
                actual = resolve_jsonpath(data, path)
            except ValueError as exc:
                results.append(
                    AssertionResult(
                        status="SKIPPED",
                        passed=None,
                        jsonpath=path,
                        operator="invalid_jsonpath",
                        expected=raw_assertions,
                        actual=None,
                        message=str(exc),
                    )
                )
                continue
            for operator, expected in self._normalize_assertions(raw_assertions).items():
                passed, message = evaluate_operator(operator, actual, expected)
                status = "SKIPPED" if passed is None else "PASS" if passed else "FAIL"
                results.append(
                    AssertionResult(
                        status=status,
                        passed=passed,
                        jsonpath=path,
                        operator=operator,
                        expected=expected,
                        actual=None if actual is MISSING else actual,
                        message=message,
                    )
                )
        return results

    def _normalize_path(self, path: str) -> str:
        return path if path.startswith("$") else f"$.{path}"

    def _normalize_assertions(self, assertions: Any) -> dict[str, Any]:
        if isinstance(assertions, dict) and any(key in OPERATORS for key in assertions):
            return {str(key): value for key, value in assertions.items() if key in OPERATORS}
        return {"equals": assertions}


assertion_engine = AssertionEngine()
