"""Backend validation orchestration."""

from __future__ import annotations

from typing import Any

from app.backend_validation.extractors.engine import VariableExtractionEngine, variable_extraction_engine
from app.backend_validation.models import BackendValidationCheck, BackendValidationSummary
from app.backend_validation.registry import BackendValidatorRegistry, backend_validator_registry


class BackendValidationEngine:
    """Build and run backend validators against completed evaluation data."""

    def __init__(
        self,
        registry: BackendValidatorRegistry | None = None,
        extraction_engine: VariableExtractionEngine | None = None,
    ) -> None:
        self.registry = registry or backend_validator_registry
        self.extraction_engine = extraction_engine or variable_extraction_engine

    def validate(self, transcript: list[Any], scenario: Any) -> BackendValidationSummary:
        config = self._validation_config(scenario)
        if not config:
            return BackendValidationSummary(
                status="not_configured",
                passed=None,
                reason="No backend validation checks were configured for this scenario.",
            )

        configs = config if isinstance(config, list) else [config]
        summaries: list[BackendValidationSummary] = []
        for item in configs:
            if not isinstance(item, dict):
                summaries.append(
                    BackendValidationSummary(
                        status="SKIPPED",
                        passed=None,
                        reason="Backend validation entry was not an object.",
                    )
                )
                continue
            item = self._with_extracted_variables(item, transcript, scenario)
            validator_type = str(item.get("type") or "rest")
            validator = self.registry.build(validator_type, item)
            summaries.append(validator.validate(transcript=transcript, scenario=scenario))

        if len(summaries) == 1:
            return summaries[0]

        checks: list[BackendValidationCheck] = []
        for summary in summaries:
            checks.extend(summary.checks)
        pass_values = [summary.passed for summary in summaries if summary.passed is not None]
        passed = all(pass_values) if pass_values else None
        status = "PASS" if passed is True else "FAIL" if passed is False else "SKIPPED"
        return BackendValidationSummary(
            status=status,
            passed=passed,
            reason=f"Executed {len(summaries)} backend validation checks.",
            checks=checks,
        )

    def _validation_config(self, scenario: Any) -> dict[str, Any] | list[Any]:
        agent = getattr(scenario, "agent", None)
        agent_config = getattr(agent, "config", None)
        if isinstance(agent_config, dict):
            config = agent_config.get("backend_validation") or agent_config.get("backend_validation_checks")
            if isinstance(config, (dict, list)):
                return self._with_backend_connections(config, agent_config.get("backend_validation_connections"))
        config = getattr(scenario, "backend_validation", None)
        if isinstance(config, (dict, list)):
            agent = getattr(scenario, "agent", None)
            agent_config = getattr(agent, "config", None)
            connections = agent_config.get("backend_validation_connections") if isinstance(agent_config, dict) else None
            return self._with_backend_connections(config, connections)
        return {}

    def _with_backend_connections(
        self,
        config: dict[str, Any] | list[Any],
        connection_catalog: Any,
    ) -> dict[str, Any] | list[Any]:
        if not isinstance(connection_catalog, dict) or not connection_catalog.get("enabled", True):
            return config
        connections = {
            item.get("id"): item
            for item in connection_catalog.get("connections") or []
            if isinstance(item, dict) and item.get("id")
        }
        if not connections:
            return config
        if isinstance(config, list):
            return [self._merge_backend_connection(item, connections) if isinstance(item, dict) else item for item in config]
        return self._merge_backend_connection(config, connections)

    def _merge_backend_connection(self, config: dict[str, Any], connections: dict[str, dict[str, Any]]) -> dict[str, Any]:
        backend_id = config.get("backend")
        if not backend_id or backend_id not in connections:
            return config
        backend = connections[backend_id]
        merged = dict(config)
        merged["backend_connection_used"] = {
            "id": backend.get("id"),
            "name": backend.get("name"),
            "type": backend.get("type"),
        }
        validator_type = str(merged.get("type") or backend.get("type") or "").lower()
        if validator_type == "rest":
            merged = self._merge_rest_backend(merged, backend)
        elif validator_type == "sql":
            merged = self._merge_sql_backend(merged, backend)
        return merged

    def _merge_rest_backend(self, config: dict[str, Any], backend: dict[str, Any]) -> dict[str, Any]:
        merged = dict(config)
        request = dict(merged.get("request") or {})
        base_url = backend.get("base_url")
        if base_url and request.get("url") and str(request["url"]).startswith("/"):
            request["url"] = str(base_url).rstrip("/") + str(request["url"])
        elif base_url and not request.get("url"):
            request["url"] = str(base_url)
        if backend.get("timeout") is not None and request.get("timeout") is None:
            request["timeout"] = backend.get("timeout")
        if backend.get("verify_ssl") is not None and request.get("verify_ssl") is None:
            request["verify_ssl"] = backend.get("verify_ssl")
        auth = backend.get("authentication") if isinstance(backend.get("authentication"), dict) else {}
        if auth.get("type") == "bearer" and request.get("bearer_token") is None:
            request["bearer_token"] = auth.get("token") or auth.get("value")
        elif auth.get("type") == "basic" and request.get("basic_auth") is None:
            request["basic_auth"] = {
                "username": auth.get("username"),
                "password": auth.get("password") or auth.get("value"),
            }
        merged["request"] = request
        return merged

    def _merge_sql_backend(self, config: dict[str, Any], backend: dict[str, Any]) -> dict[str, Any]:
        merged = dict(config)
        connection = dict(merged.get("connection") or {})
        for key in ("driver", "connection_string"):
            if backend.get(key) is not None:
                connection[key] = backend[key]
        merged["connection"] = connection
        return merged

    def _with_extracted_variables(
        self,
        config: dict[str, Any],
        transcript: list[Any],
        scenario: Any,
    ) -> dict[str, Any]:
        extracted = self.extraction_engine.extract(
            transcript,
            self._evaluation_context(scenario),
            config,
        )
        if not extracted and not self.extraction_engine.has_extraction_config(config):
            return config
        updated = dict(config)
        variables = self._static_variables(config.get("variables"))
        variables.update(extracted)
        updated["variables"] = variables
        updated["extracted_variables"] = extracted
        return updated

    def _static_variables(self, variables: Any) -> dict[str, Any]:
        if not isinstance(variables, dict):
            return {}
        static: dict[str, Any] = {}
        for key, value in variables.items():
            if isinstance(value, dict) and any(marker in value for marker in ("regex", "speaker", "source", "path")):
                continue
            static[str(key)] = value
        return static

    def _evaluation_context(self, scenario: Any) -> dict[str, Any]:
        context: dict[str, Any] = {"scenario": scenario}
        context["scenario_id"] = getattr(scenario, "scenario_id", None)
        agent = getattr(scenario, "agent", None)
        agent_config = getattr(agent, "config", None)
        if isinstance(agent_config, dict):
            context.update(agent_config)
        return context


backend_validation_engine = BackendValidationEngine()
