"""JSON-path backend validation variable extraction."""

from __future__ import annotations

from typing import Any

from app.backend_validation.extractors.base import BaseVariableExtractor


class JsonVariableExtractor(BaseVariableExtractor):
    def extract(
        self,
        transcript: list[Any],
        evaluation_context: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        variables = config.get("variables") if isinstance(config.get("variables"), dict) else {}
        extracted: dict[str, Any] = {}
        for name, variable_config in variables.items():
            if not isinstance(variable_config, dict) or not variable_config.get("path"):
                continue
            source = str(variable_config.get("source") or "metadata").lower()
            path = str(variable_config["path"])
            for candidate in self._source_values(source, transcript, evaluation_context):
                value = self._json_path(candidate, path)
                if value is not None:
                    extracted[str(name)] = value
                    break
        return extracted

    def _source_values(
        self,
        source: str,
        transcript: list[Any],
        evaluation_context: dict[str, Any],
    ) -> list[Any]:
        if source in {"context", "evaluation_context"}:
            return [evaluation_context]
        values = []
        for message in transcript or []:
            if source == "metadata":
                values.append(self._message_value(message, "metadata"))
            elif source == "interaction_evidence":
                values.append(self._message_value(message, "interaction_evidence"))
            else:
                values.append(self._message_value(message, source))
        return values

    def _message_value(self, message: Any, key: str) -> Any:
        if isinstance(message, dict):
            return message.get(key)
        return getattr(message, key, None)

    def _json_path(self, data: Any, path: str) -> Any:
        if path.startswith("$."):
            path = path[2:]
        elif path == "$":
            return data
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
