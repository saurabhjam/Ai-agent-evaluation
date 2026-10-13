from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


class BrowserTokenConfigurationError(ValueError):
    """Raised when browser_token auth is missing a valid extraction strategy."""


BrowserTokenStrategy = Literal["network", "script"]


@dataclass(frozen=True)
class BrowserTokenExtractionConfig:
    strategy: BrowserTokenStrategy
    script: str | None = None
    intercept_pattern: str | None = None
    token_path: str | None = None


def resolve_browser_token_strategy(auth: dict[str, Any]) -> BrowserTokenExtractionConfig:
    script = _clean(auth.get("script"))
    intercept_pattern = _clean(auth.get("intercept_pattern"))
    token_path = _clean(auth.get("token_path"))

    if script:
        return BrowserTokenExtractionConfig(strategy="script", script=script)

    has_intercept = bool(intercept_pattern)
    has_token_path = bool(token_path)
    if has_intercept and has_token_path:
        return BrowserTokenExtractionConfig(
            strategy="network",
            intercept_pattern=intercept_pattern,
            token_path=token_path,
        )

    if not has_intercept and not has_token_path:
        raise BrowserTokenConfigurationError(
            "Browser token authentication is incomplete: missing intercept_pattern and token_path."
        )

    if has_intercept:
        raise BrowserTokenConfigurationError(
            "Browser token authentication is incomplete: missing token_path."
        )
    if has_token_path:
        raise BrowserTokenConfigurationError(
            "Browser token authentication is incomplete: missing intercept_pattern."
        )
    raise BrowserTokenConfigurationError(
        "Browser token authentication requires either a script or intercept_pattern plus token_path."
    )


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
