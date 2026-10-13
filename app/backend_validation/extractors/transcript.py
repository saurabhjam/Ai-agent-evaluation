"""Transcript-scoped backend validation variable extraction."""

from __future__ import annotations

import re
from typing import Any

from app.backend_validation.extractors.base import BaseVariableExtractor


class TranscriptVariableExtractor(BaseVariableExtractor):
    def extract(
        self,
        transcript: list[Any],
        evaluation_context: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        variables = config.get("variables") if isinstance(config.get("variables"), dict) else {}
        extracted: dict[str, Any] = {}
        for name, variable_config in variables.items():
            if not isinstance(variable_config, dict) or not variable_config.get("regex"):
                continue
            speaker = str(variable_config.get("speaker") or "").lower()
            source = str(variable_config.get("source") or "content").lower()
            if not speaker and source == "content":
                continue
            pattern = str(variable_config["regex"])
            for message in transcript or []:
                if speaker and self._role(message) != speaker:
                    continue
                text = self._source_text(message, source)
                match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
                if match:
                    extracted[str(name)] = match.group(1) if match.groups() else match.group(0)
                    break
        return extracted

    def _role(self, message: Any) -> str:
        if isinstance(message, dict):
            return str(message.get("role") or message.get("speaker") or "").lower()
        return str(getattr(message, "role", None) or getattr(message, "speaker", None) or "").lower()

    def _source_text(self, message: Any, source: str) -> str:
        if source in {"metadata", "interaction_evidence"}:
            value = self._message_value(message, source)
            return str(value or "")
        return str(
            self._message_value(message, "content")
            or self._message_value(message, "message")
            or ""
        )

    def _message_value(self, message: Any, key: str) -> Any:
        if isinstance(message, dict):
            return message.get(key)
        return getattr(message, key, None)
