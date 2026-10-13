"""Assertion operators for backend validation."""

from __future__ import annotations

import re
from typing import Any

from app.backend_validation.assertions.jsonpath import MISSING


def evaluate_operator(operator: str, actual: Any, expected: Any) -> tuple[bool | None, str]:
    if operator == "exists":
        passed = actual is not MISSING
        return passed, "Value exists." if passed else "Value does not exist."
    if operator == "not_exists":
        passed = actual is MISSING
        return passed, "Value does not exist." if passed else "Value exists."
    if actual is MISSING:
        return False, "JSONPath did not resolve to a value."

    if operator == "equals":
        passed = actual == expected
        return passed, f"Expected {actual!r} to equal {expected!r}."
    if operator == "not_equals":
        passed = actual != expected
        return passed, f"Expected {actual!r} to not equal {expected!r}."
    if operator == "contains":
        passed = _contains(actual, expected)
        return passed, f"Expected {actual!r} to contain {expected!r}."
    if operator == "starts_with":
        passed = str(actual).startswith(str(expected))
        return passed, f"Expected {actual!r} to start with {expected!r}."
    if operator == "ends_with":
        passed = str(actual).endswith(str(expected))
        return passed, f"Expected {actual!r} to end with {expected!r}."
    if operator == "greater_than":
        return _compare(actual, expected, lambda left, right: left > right, ">")
    if operator == "greater_than_or_equal":
        return _compare(actual, expected, lambda left, right: left >= right, ">=")
    if operator == "less_than":
        return _compare(actual, expected, lambda left, right: left < right, "<")
    if operator == "less_than_or_equal":
        return _compare(actual, expected, lambda left, right: left <= right, "<=")
    if operator == "in":
        passed = isinstance(expected, list) and actual in expected
        return passed, f"Expected {actual!r} to be in {expected!r}."
    if operator == "not_in":
        passed = isinstance(expected, list) and actual not in expected
        return passed, f"Expected {actual!r} to not be in {expected!r}."
    if operator == "length":
        try:
            actual_length = len(actual)
        except TypeError:
            return False, f"Value {actual!r} has no length."
        passed = actual_length == expected
        return passed, f"Expected length {actual_length!r} to equal {expected!r}."
    if operator == "regex":
        passed = re.search(str(expected), str(actual)) is not None
        return passed, f"Expected {actual!r} to match regex {expected!r}."
    return None, f"Unsupported assertion operator: {operator}."


def _contains(actual: Any, expected: Any) -> bool:
    if isinstance(actual, dict):
        return expected in actual
    if isinstance(actual, (list, tuple, set)):
        return expected in actual
    return str(expected) in str(actual)


def _compare(actual: Any, expected: Any, comparator: Any, symbol: str) -> tuple[bool, str]:
    try:
        left = float(actual)
        right = float(expected)
    except (TypeError, ValueError):
        return False, f"Could not compare {actual!r} {symbol} {expected!r}."
    passed = comparator(left, right)
    return passed, f"Expected {left!r} {symbol} {right!r}."
