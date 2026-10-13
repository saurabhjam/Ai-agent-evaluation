"""Backend validation variable extraction orchestration."""

from __future__ import annotations

from typing import Any

from app.backend_validation.extractors.base import BaseVariableExtractor
from app.backend_validation.extractors.json import JsonVariableExtractor
from app.backend_validation.extractors.regex import RegexVariableExtractor
from app.backend_validation.extractors.transcript import TranscriptVariableExtractor


class VariableExtractionEngine:
    def __init__(self, extractors: list[BaseVariableExtractor] | None = None) -> None:
        self.extractors = extractors or [
            RegexVariableExtractor(),
            TranscriptVariableExtractor(),
            JsonVariableExtractor(),
        ]

    def extract(
        self,
        transcript: list[Any],
        evaluation_context: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.has_extraction_config(config):
            return {}
        extracted: dict[str, Any] = {}
        for extractor in self.extractors:
            extracted.update(extractor.extract(transcript, evaluation_context, config))
        return extracted

    def has_extraction_config(self, config: dict[str, Any]) -> bool:
        variables = config.get("variables")
        if not isinstance(variables, dict):
            return False
        for value in variables.values():
            if isinstance(value, dict) and any(key in value for key in ("regex", "speaker", "source", "path")):
                return True
        return False


variable_extraction_engine = VariableExtractionEngine()
