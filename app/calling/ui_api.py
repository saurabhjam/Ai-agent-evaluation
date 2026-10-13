"""HTTP API for AI Calling Agent Evaluation UI integration."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, SecretStr, field_validator

from app.calling.config import CallingProviderConfig, default_mock_provider_config
from app.calling.evaluation_bridge import CallingEvaluationBridge
from app.calling.evaluation_runner import CallingEvaluationRuntimeRunner
from app.calling.execution_result import CallingExecutionResult, CallingExecutionStatus
from app.calling.models import CallDirection
from app.evaluation_service import EvaluationResult
from app.evaluation_store import new_evaluation_id, save_evaluation_report
from app.schemas import TestScenario


router = APIRouter(prefix="/calling", tags=["AI Calling"])

_ROOT = Path(__file__).resolve().parents[2]
_STORE_PATH = _ROOT / "calling_connections.json"
_SCENARIOS_DIR = _ROOT / "scenarios"

CallingProviderName = Literal["mock", "vapi", "twilio", "retell", "bland", "sip", "custom"]
CallingRunStatus = Literal[
    "connecting",
    "calling",
    "waiting_for_transcript",
    "evaluating",
    "completed",
    "failed",
]


class CallingConnectionInput(BaseModel):
    """Client-facing calling connection configuration."""

    name: str
    provider: CallingProviderName
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, SecretStr | str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name is required")
        return value.strip()


class CallingConnectionResponse(BaseModel):
    """Credential-safe calling connection response."""

    id: str
    name: str
    provider: str
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, str] = Field(default_factory=dict)
    status: str = "configured"
    created_at: str
    updated_at: str


class CallingConnectionPatch(BaseModel):
    name: Optional[str] = None
    provider: Optional[CallingProviderName] = None
    enabled: Optional[bool] = None
    config: Optional[dict[str, Any]] = None
    credentials: Optional[dict[str, SecretStr | str]] = None


class CallingConnectionTestResult(BaseModel):
    success: bool
    status: str
    message: str
    provider: str
    checks: list[str] = Field(default_factory=list)


class CallingRunRequest(BaseModel):
    scenario_path: str
    direction: CallDirection = CallDirection.outbound
    to_number: Optional[str] = None
    from_number: Optional[str] = None


class CallingRunResponse(BaseModel):
    evaluation_id: Optional[str] = None
    success: bool
    status: CallingRunStatus
    connection_id: str
    provider: str
    evaluation: Optional[EvaluationResult] = None
    execution: Optional[CallingExecutionResult] = None
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    recording_metadata: list[dict[str, Any]] = Field(default_factory=list)
    recording_status: str = "unavailable"
    conversation_audio: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    status_events: list[dict[str, Any]] = Field(default_factory=list)
    report: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_store() -> dict[str, dict[str, Any]]:
    if not _STORE_PATH.exists():
        return {}
    with _STORE_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _save_store(data: dict[str, dict[str, Any]]) -> None:
    with _STORE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)


def _secret_value(value: SecretStr | str) -> str:
    return value.get_secret_value() if isinstance(value, SecretStr) else str(value)


def _safe_connection(raw: dict[str, Any]) -> CallingConnectionResponse:
    credentials = raw.get("credentials") or {}

    return CallingConnectionResponse(
        id=raw["id"],
        name=raw["name"],
        provider=raw["provider"],
        enabled=raw.get("enabled", True),
        config=raw.get("config") or {},
        credentials={key: "configured" for key, value in credentials.items() if value},
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
    )


def _provider_requirements(provider: str) -> dict[str, list[str]]:
    return {
        "mock": {"config": [], "credentials": []},
        "twilio": {"config": ["from_number", "voice_url"], "credentials": ["account_sid", "auth_token"]},
        "vapi": {"config": ["assistant_id"], "credentials": ["api_key"]},
        "retell": {"config": ["agent_id", "from_number"], "credentials": ["api_key"]},
        "bland": {"config": ["pathway_id", "from_number"], "credentials": ["api_key"]},
        "sip": {"config": ["sip_uri"], "credentials": ["username", "password"]},
        "custom": {"config": ["endpoint"], "credentials": []},
    }.get(provider, {"config": [], "credentials": []})


def _validate_connection(raw: dict[str, Any]) -> CallingConnectionTestResult:
    provider = raw["provider"]
    config = raw.get("config") or {}
    credentials = raw.get("credentials") or {}
    requirements = _provider_requirements(provider)
    checks: list[str] = []
    missing: list[str] = []

    for field in requirements["config"]:
        if not config.get(field):
            missing.append(field)
        else:
            checks.append(f"config:{field}")
    for field in requirements["credentials"]:
        if not credentials.get(field):
            missing.append(field)
        else:
            checks.append(f"credential:{field}")

    if missing:
        return CallingConnectionTestResult(
            success=False,
            status="configuration_error",
            message="Missing required fields: " + ", ".join(missing),
            provider=provider,
            checks=checks,
        )

    if provider == "vapi":
        from app.calling.config import CallingProviderConfig
        from app.calling.providers.vapi_validator import VapiConnectionValidator

        try:
            validation = VapiConnectionValidator(
                CallingProviderConfig(
                    provider_name="vapi",
                    credentials=credentials,
                    settings=config,
                )
            ).validate()
        except Exception as exc:
            return CallingConnectionTestResult(
                success=False,
                status="configuration_error",
                message=f"Vapi validation failed: {type(exc).__name__}: {exc}",
                provider=provider,
                checks=checks,
            )
        return CallingConnectionTestResult(
            success=validation.success,
            status="configured" if validation.success else "configuration_error",
            message=validation.message,
            provider=provider,
            checks=validation.checks,
        )

    runtime_note = (
        "Mock calling runtime is available."
        if provider == "mock"
        else "Configuration is valid. Runtime execution currently uses the provider-neutral calling pipeline; real provider execution requires the provider runtime to be explicitly wired."
    )
    return CallingConnectionTestResult(
        success=True,
        status="configured",
        message=runtime_note,
        provider=provider,
        checks=checks or ["basic configuration"],
    )


def _load_scenario(path_value: str) -> TestScenario:
    path = Path(path_value)
    if not path.is_absolute():
        path = _ROOT / path
    try:
        resolved = path.resolve()
        root = _ROOT.resolve()
        if root not in resolved.parents and resolved != root:
            raise ValueError("Scenario path must stay inside the project")
        with resolved.open("r", encoding="utf-8") as handle:
            return TestScenario(**yaml.safe_load(handle))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scenario not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid scenario: {exc}") from exc


def _provider_config(raw: dict[str, Any]) -> CallingProviderConfig:
    provider = raw["provider"]
    config = raw.get("config") or {}
    rag_config = config.get("rag_config")
    
    return CallingProviderConfig(
        provider_name=provider,
        credentials=raw.get("credentials") or {},
        settings=config,
        metadata={
            "configured_provider": provider,
            "ui_provider_mode": "real_runtime",
            **({"rag_config": rag_config} if rag_config else {}),
        }
    )


def _status_events(execution: CallingExecutionResult, provider: str) -> list[dict[str, Any]]:
    labels = {
        "started": "Connecting",
        "connected": "Calling",
        "in_progress": "Waiting for Transcript",
        "completed": "Evaluating",
        "failed": "Failed",
        "timed_out": "Failed",
        "cancelled": "Failed",
    }
    events = [
        {
            "status": event.event_type.value,
            "label": labels.get(event.event_type.value, event.event_type.value),
            "timestamp": event.timestamp,
            "metadata": event.metadata,
        }
        for event in execution.execution_events
    ]
    if execution.status == CallingExecutionStatus.completed:
        events.append({"status": "completed", "label": "Completed", "timestamp": _now(), "metadata": {"provider": provider}})
    return events


def _transcript(execution: CallingExecutionResult) -> list[dict[str, Any]]:
    conversation = execution.normalized_conversation
    if not conversation:
        return []
    return [
        {
            "speaker": "customer" if message.role == "simulated_user" else message.role,
            "text": message.content,
            "turn_index": message.turn_index,
            "timestamp": message.timestamp,
            "metadata": message.metadata or {},
        }
        for message in conversation.messages
    ]


def _recording_metadata(execution: CallingExecutionResult) -> list[dict[str, Any]]:
    evidence = execution.conversation_evidence
    if not evidence:
        return []
    return [
        recording.model_dump(mode="json")
        for recording in evidence.recordings
    ]


def _recording_status(recordings: list[dict[str, Any]]) -> str:
    if not recordings:
        return "unavailable"
    for recording in recordings:
        metadata = recording.get("metadata") or {}
        status_value = (
            recording.get("status")
            or metadata.get("status")
            or metadata.get("recording_status")
            or metadata.get("provider_json", {}).get("status")
        )
        if str(status_value or "").lower() in {"processing", "in-progress", "queued"}:
            return "processing"
    return "available"


def _conversation_audio(recordings: list[dict[str, Any]]) -> dict[str, Any]:
    audio = {
        "full": None,
        "agent": None,
        "customer": None,
        "metadata": {},
    }
    for index, recording in enumerate(recordings):
        metadata = recording.get("metadata") or {}
        provider_json = metadata.get("provider_json") or {}
        source = (
            recording.get("remote_url")
            or recording.get("url")
            or recording.get("recording_url")
            or recording.get("media_url")
            or metadata.get("remote_url")
            or metadata.get("recording_url")
            or metadata.get("media_url")
            or provider_json.get("recordingUrl")
            or provider_json.get("recording_url")
            or provider_json.get("stereoRecordingUrl")
        )
        label = _audio_channel(recording, index)
        audio[label] = source
        audio["metadata"][label] = {
            "duration": recording.get("duration_seconds"),
            "sample_rate": recording.get("sample_rate"),
            "format": recording.get("format"),
            "channels": recording.get("channels"),
            "provider": recording.get("provider_name") or recording.get("provider"),
        }
        if provider_json.get("assistantRecordingUrl") or provider_json.get("assistant_recording_url"):
            audio["agent"] = provider_json.get("assistantRecordingUrl") or provider_json.get("assistant_recording_url")
        if provider_json.get("customerRecordingUrl") or provider_json.get("customer_recording_url"):
            audio["customer"] = provider_json.get("customerRecordingUrl") or provider_json.get("customer_recording_url")
    return audio


def _audio_channel(recording: dict[str, Any], index: int) -> str:
    source = " ".join(
        str(item)
        for item in [
            recording.get("name"),
            recording.get("channel"),
            recording.get("type"),
            recording.get("artifact_type"),
            (recording.get("metadata") or {}).get("channel"),
            (recording.get("metadata") or {}).get("type"),
        ]
        if item
    ).lower()
    if "assistant" in source or "agent" in source:
        return "agent"
    if "customer" in source or "caller" in source or "user" in source:
        return "customer"
    return "full" if index == 0 else f"full_{index + 1}"


def _persist_calling_response(
    *,
    response: CallingRunResponse,
    scenario: TestScenario | None,
) -> CallingRunResponse:
    payload = response.model_dump(mode="json")
    execution = response.execution
    evaluation = response.evaluation
    session = execution.call_session if execution else None
    payload.update(
        {
            "evaluation_id": response.evaluation_id or new_evaluation_id(),
            "agent_id": response.connection_id,
            "agent_type": "calling",
            "adapter": response.provider,
            "scenario_id": scenario.scenario_id if scenario else None,
            "session_id": session.session_id if session else None,
            "provider_call_id": session.provider_call_id if session else None,
            "started_at": session.started_at if session else None,
            "ended_at": session.ended_at if session else None,
            "duration_seconds": response.execution.duration_seconds if response.execution else None,
            "overall_score": evaluation.overall_score if evaluation else None,
            "passed": evaluation.passed if evaluation else False,
            "conversation": [turn.model_dump(mode="json") for turn in evaluation.conversation] if evaluation else [],
            "metrics": [metric.model_dump(mode="json") for metric in evaluation.metrics] if evaluation else [],
            "rag_evaluation": evaluation.rag_evaluation.model_dump(mode="json") if evaluation and evaluation.rag_evaluation else None,
            "complete_report": payload.get("report") or {},
        }
    )
    saved = save_evaluation_report(payload)
    return response.model_copy(update={"evaluation_id": saved["evaluation_id"]})


@router.get("/providers")
def list_calling_providers() -> dict[str, Any]:
    """Return provider options and dynamic form fields for the UI."""
    return {
        "providers": [
            {"id": "mock", "label": "Mock", "runtime": "available"},
            {"id": "vapi", "label": "Vapi", "runtime": "config_only"},
            {"id": "twilio", "label": "Twilio", "runtime": "provider_boundary_available"},
            {"id": "retell", "label": "Retell", "runtime": "config_only"},
            {"id": "bland", "label": "Bland", "runtime": "config_only"},
            {"id": "sip", "label": "SIP", "runtime": "config_only"},
            {"id": "custom", "label": "Custom", "runtime": "config_only"},
        ],
        "requirements": {provider: _provider_requirements(provider) for provider in ["mock", "vapi", "twilio", "retell", "bland", "sip", "custom"]},
    }


@router.get("/connections", response_model=list[CallingConnectionResponse])
def list_calling_connections() -> list[CallingConnectionResponse]:
    store = _load_store()
    return [_safe_connection(item) for item in store.values()]


@router.post("/connections", response_model=CallingConnectionResponse, status_code=status.HTTP_201_CREATED)
def create_calling_connection(payload: CallingConnectionInput) -> CallingConnectionResponse:
    store = _load_store()
    connection_id = f"calling_{uuid.uuid4().hex[:12]}"
    now = _now()
    raw = {
        "id": connection_id,
        "name": payload.name,
        "provider": payload.provider,
        "enabled": payload.enabled,
        "config": payload.config,
        "credentials": {key: _secret_value(value) for key, value in payload.credentials.items()},
        "created_at": now,
        "updated_at": now,
    }
    store[connection_id] = raw
    _save_store(store)
    return _safe_connection(raw)


@router.get("/connections/{connection_id}", response_model=CallingConnectionResponse)
def get_calling_connection(connection_id: str) -> CallingConnectionResponse:
    raw = _load_store().get(connection_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Calling connection not found")
    return _safe_connection(raw)


@router.patch("/connections/{connection_id}", response_model=CallingConnectionResponse)
def update_calling_connection(connection_id: str, payload: CallingConnectionPatch) -> CallingConnectionResponse:
    store = _load_store()
    raw = store.get(connection_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Calling connection not found")
    if payload.name is not None:
        raw["name"] = payload.name.strip()
    if payload.provider is not None:
        raw["provider"] = payload.provider
    if payload.enabled is not None:
        raw["enabled"] = payload.enabled
    if payload.config is not None:
        raw["config"] = payload.config
    if payload.credentials is not None:
        existing = raw.get("credentials") or {}
        updates = {key: _secret_value(value) for key, value in payload.credentials.items()}
        raw["credentials"] = {**existing, **{key: value for key, value in updates.items() if value}}

    raw["updated_at"] = _now()
    store[connection_id] = raw
    _save_store(store)
    return _safe_connection(raw)


@router.delete("/connections/{connection_id}")
def delete_calling_connection(connection_id: str) -> dict[str, Any]:
    store = _load_store()
    if connection_id not in store:
        raise HTTPException(status_code=404, detail="Calling connection not found")
    del store[connection_id]
    _save_store(store)
    return {"success": True, "message": "Calling connection deleted"}


@router.post("/connections/{connection_id}/test", response_model=CallingConnectionTestResult)
def test_calling_connection(connection_id: str) -> CallingConnectionTestResult:
    raw = _load_store().get(connection_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Calling connection not found")
    return _validate_connection(raw)


@router.post("/connections/{connection_id}/run", response_model=CallingRunResponse)
def run_calling_evaluation(connection_id: str, payload: CallingRunRequest) -> CallingRunResponse:
    raw = _load_store().get(connection_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Calling connection not found")
    if not raw.get("enabled", True):
        raise HTTPException(status_code=400, detail="Calling connection is disabled")

    validation = _validate_connection(raw)
    if not validation.success:
        return CallingRunResponse(
            success=False,
            status="failed",
            connection_id=connection_id,
            provider=raw["provider"],
            error=validation.message,
            created_at=_now(),
        )

    scenario = _load_scenario(payload.scenario_path)
    provider_config = _provider_config(raw)

    config = raw.get("config") or {}
    to_number = payload.to_number or "+15550000002"
    from_number = payload.from_number or config.get("from_number") or "+15550000001"

    try:
        execution = CallingEvaluationRuntimeRunner().run(
            scenario,
            provider_config=provider_config,
            direction=payload.direction,
            to=to_number,
            from_=from_number,
        )
        if not execution.success or execution.normalized_conversation is None:
            response = CallingRunResponse(
                success=False,
                status="failed",
                connection_id=connection_id,
                provider=raw["provider"],
                execution=execution,
                status_events=_status_events(execution, raw["provider"]),
                report={
                    "provider_runtime": provider_config.provider_name,
                    "configured_provider": raw["provider"],
                    "transcript_source": None,
                    "recording_source": "unavailable",
                },
                error=execution.error or "Calling execution failed before evaluation.",
                created_at=_now(),
            )
            return _persist_calling_response(response=response, scenario=scenario)
        evaluation = CallingEvaluationBridge().evaluate(execution, scenario)
        transcript = _transcript(execution)
        recordings = _recording_metadata(execution)
        recording_status = _recording_status(recordings)
        conversation_audio = _conversation_audio(recordings)
        artifacts = [artifact.model_dump(mode="json") for artifact in execution.artifacts]
        report = {
            "overall_score": evaluation.overall_score,
            "passed": evaluation.passed,
            "metrics": [metric.model_dump(mode="json") for metric in evaluation.metrics],
            "rag_evaluation": evaluation.rag_evaluation.model_dump(mode="json") if evaluation.rag_evaluation else None,
            "provider_runtime": provider_config.provider_name,
            "configured_provider": raw["provider"],
            "recording_status": recording_status,
            "conversation_audio": conversation_audio,
        }
        response = CallingRunResponse(
            success=evaluation.success,
            status="completed" if evaluation.success else "failed",
            connection_id=connection_id,
            provider=raw["provider"],
            evaluation=evaluation,
            execution=execution,
            transcript=transcript,
            recording_metadata=recordings,
            recording_status=recording_status,
            conversation_audio=conversation_audio,
            artifacts=artifacts,
            status_events=_status_events(execution, raw["provider"]),
            report=report,
            error=evaluation.error,
            created_at=_now(),
        )
        return _persist_calling_response(response=response, scenario=scenario)
    except Exception as exc:
        return CallingRunResponse(
            success=False,
            status="failed",
            connection_id=connection_id,
            provider=raw["provider"],
            error=f"{type(exc).__name__}: {exc}",
            created_at=_now(),
        )
