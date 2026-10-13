"""Regex-based backend validation variable extraction."""

from __future__ import annotations

import re
from typing import Any

from app.backend_validation.extractors.base import BaseVariableExtractor


class RegexVariableExtractor(BaseVariableExtractor):
    def extract(
        self,
        transcript: list[Any],
        evaluation_context: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        variables = config.get("variables") if isinstance(config.get("variables"), dict) else {}
        text = "\n".join(self._message_text(message) for message in transcript or [])
        extracted: dict[str, Any] = {}
        for name, variable_config in variables.items():
            if not self._uses_regex(variable_config) or self._has_speaker_filter(variable_config):
                continue
            match = re.search(str(variable_config["regex"]), text, re.IGNORECASE | re.MULTILINE)
            if match:
                extracted[str(name)] = match.group(1) if match.groups() else match.group(0)
        return extracted

    def _message_text(self, message: Any) -> str:
        if isinstance(message, dict):
            return str(message.get("content") or message.get("message") or "")
        return str(getattr(message, "content", None) or getattr(message, "message", None) or "")

    def _uses_regex(self, variable_config: Any) -> bool:
        return isinstance(variable_config, dict) and bool(variable_config.get("regex"))

    def _has_speaker_filter(self, variable_config: Any) -> bool:
        return isinstance(variable_config, dict) and bool(variable_config.get("speaker"))
