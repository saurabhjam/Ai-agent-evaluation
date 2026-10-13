"""
Connection API — Phase 4 of the Universal Agent Connection System.

Exposes connection onboarding and testing through HTTP endpoints.

Endpoints
─────────
  POST   /connections             - Create a new connection
  POST   /connections/{id}/test   - Test the connection
  GET    /connections             - List all connections
  GET    /connections/{id}        - Get a specific connection
  DELETE /connections/{id}        - Remove a connection
  PATCH  /connections/{id}        - Update safe fields (name, enabled)

Security
────────
Credentials are NEVER returned in responses. The `AgentConnectionResponse`
model scrubs them out.
"""

from __future__ import annotations

import logging
import yaml
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from app.connections.input import AgentConnectionInput, ConnectionConfig
from app.connections.parser import connect_and_test, parse_connection_input
from app.connections.result import ConnectionTestResult
from app.connections.storage import repository
from app.evaluation_service import EvaluationResult, EvaluationService
from app.evaluation_store import save_evaluation_report
from app.executor import ScenarioExecutor
from app.schemas import TestScenario
from app.connections.browser_auth import BrowserAuthCheck, browser_auth_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["Connections"])


def _safe_connection_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not config:
        return None

    safe = dict(config)
    auth = safe.get("auth")
    if isinstance(auth, dict):
        safe_auth = dict(auth)
        if safe_auth.get("type") == "browser_token":
            safe_auth["value"] = "browser_token"
        elif "value" in safe_auth:
            safe_auth["value"] = ""
        safe["auth"] = safe_auth

    rag_config = safe.get("rag_config")
    if isinstance(rag_config, dict):
        safe_rag = dict(rag_config)
        evidence_request = safe_rag.get("evidence_request")
        if isinstance(evidence_request, dict):
            safe_request = dict(evidence_request)
            evidence_auth = safe_request.get("auth")
            if isinstance(evidence_auth, dict):
                safe_evidence_auth = dict(evidence_auth)
                if "value" in safe_evidence_auth:
                    safe_evidence_auth["value"] = ""
                safe_request["auth"] = safe_evidence_auth
            safe_rag["evidence_request"] = safe_request
        safe["rag_config"] = safe_rag
    return safe


def _safe_backend_validation_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not config:
        return None
    safe = dict(config)
    connections = []
    for item in safe.get("connections") or []:
        if not isinstance(item, dict):
            continue
        safe_item = dict(item)
        auth = safe_item.get("authentication")
        if isinstance(auth, dict):
            safe_auth = dict(auth)
            for key in ("token", "password", "value", "api_key"):
                if key in safe_auth:
                    safe_auth[key] = "******"
            safe_item["authentication"] = safe_auth
        if safe_item.get("connection_string"):
            safe_item["connection_string"] = "******"
        connections.append(safe_item)
    safe["connections"] = connections
    return safe


def _merge_backend_validation_into_scenario(scenario: TestScenario, connection: Any) -> TestScenario:
    backend_config = getattr(connection, "backend_validation", None)
    if not backend_config:
        return scenario
    agent_config = dict(scenario.agent.config or {})
    agent_config["backend_validation_connections"] = backend_config
    scenario.agent.config = agent_config
    return scenario


def _merge_backend_validation_patch(existing: dict[str, Any] | None, incoming: dict[str, Any] | None) -> dict[str, Any] | None:
    if incoming is None:
        return existing
    if not existing:
        return incoming
    existing_by_id = {
        item.get("id"): item
        for item in existing.get("connections") or []
        if isinstance(item, dict) and item.get("id")
    }
    merged = dict(incoming)
    merged_connections = []
    for item in incoming.get("connections") or []:
        if not isinstance(item, dict):
            continue
        updated = dict(item)
        original = existing_by_id.get(updated.get("id"), {})
        if updated.get("connection_string") == "******" and original.get("connection_string"):
            updated["connection_string"] = original["connection_string"]
        auth = updated.get("authentication")
        original_auth = original.get("authentication") if isinstance(original.get("authentication"), dict) else {}
        if isinstance(auth, dict):
            safe_auth = dict(auth)
            for key in ("token", "password", "value", "api_key"):
                if safe_auth.get(key) == "******" and original_auth.get(key):
                    safe_auth[key] = original_auth[key]
            updated["authentication"] = safe_auth
        merged_connections.append(updated)
    merged["connections"] = merged_connections
    return merged


# ===========================================================================
# Response Models (Credential-Safe)
# ===========================================================================

class AgentConnectionResponse(BaseModel):
    """
    Safe representation of a connection for API responses.
    No credentials or raw config dicts are exposed.
    """
    id: str
    name: str
    type: str
    adapter: str
    enabled: bool
    status: str = "configured"
    config: dict[str, Any] | None = None
    backend_validation: dict[str, Any] | None = None

    @classmethod
    def from_connection(cls, conn: Any) -> "AgentConnectionResponse":
        return cls(
            id=conn.id,
            name=conn.name,
            type=conn.type.value,
            adapter=conn.adapter,
            enabled=conn.enabled,
            config=_safe_connection_config(conn.config),
            backend_validation=_safe_backend_validation_config(getattr(conn, "backend_validation", None)),
        )


class ConnectionPatchInput(BaseModel):
    """
    Input for PATCH /connections/{id}.
    Supports legacy safe field patches and full connection edits.
    """
    name: str | None = None
    enabled: bool | None = None
    type: str | None = None
    connection: ConnectionConfig | None = None
    backend_validation: dict[str, Any] | None = None


class EvaluationRequest(BaseModel):
    """
    Input for POST /connections/{id}/evaluate.
    References a scenario by its relative path.
    """
    scenario_path: str
    evaluation_id: str | None = None


class BrowserAuthStartRequest(BaseModel):
    url: str

class BrowserAuthStartResponse(BaseModel):
    session_id: str

class BrowserAuthSaveRequest(BaseModel):
    session_id: str
    connection_name: str
    expected_url: str | None = None
    authenticated_selector: str | None = None
    required_cookie: str | None = None
    timeout_seconds: float = Field(180.0, ge=1.0, le=600.0)

class BrowserAuthSaveResponse(BaseModel):
    storage_state_path: str
    authentication_detected_before_save: bool = False
    storage_state_saved: bool = False
    fresh_context_restored: bool = False
    authenticated_ui_detected_after_restore: bool = False

# ===========================================================================
# Endpoints
# ===========================================================================

@router.post("", response_model=AgentConnectionResponse, status_code=status.HTTP_201_CREATED)
def create_connection(input_data: AgentConnectionInput):
    """
    Create and save a new agent connection.
    """
    try:
        connection = parse_connection_input(input_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    
    repository.save(connection)
    return AgentConnectionResponse.from_connection(connection)


@router.post("/{connection_id}/test", response_model=ConnectionTestResult)
def test_connection_endpoint(connection_id: str):
    """
    Test connectivity for a saved agent connection.
    """
    connection = repository.get(connection_id)
    if not connection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")

    from app.connections.manager import ConnectionManager
    manager = ConnectionManager()
    
    try:
        result = manager.test_connection(connection)
    except Exception as e:
        logger.error(f"Unexpected error testing connection {connection_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected internal error during connection test"
        )
    
    return result


@router.get("", response_model=list[AgentConnectionResponse])
def list_connections():
    """
    List all saved agent connections.
    """
    connections = repository.list_all()
    return [AgentConnectionResponse.from_connection(c) for c in connections]


@router.get("/{connection_id}", response_model=AgentConnectionResponse)
def get_connection(connection_id: str):
    """
    Get a specific agent connection.
    """
    connection = repository.get(connection_id)
    if not connection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    
    return AgentConnectionResponse.from_connection(connection)


@router.delete("/{connection_id}", status_code=status.HTTP_200_OK)
def delete_connection(connection_id: str):
    """
    Delete a saved agent connection.
    """
    deleted = repository.delete(connection_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    
    return {"success": True, "message": "Connection deleted"}


@router.patch("/{connection_id}", response_model=AgentConnectionResponse)
def update_connection(connection_id: str, patch_data: ConnectionPatchInput):
    """
    Enable/disable or rename an existing connection.
    """
    connection = repository.get(connection_id)
    if not connection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    
    if patch_data.connection is not None or patch_data.type is not None:
        if patch_data.connection is not None:
            if patch_data.connection.options is None:
                patch_data.connection.options = {}
            for k, v in connection.config.items():
                if k not in ["endpoint", "base_url", "server_url", "selectors"] and k not in patch_data.connection.options:
                    patch_data.connection.options[k] = v
        try:
            replacement = parse_connection_input(
                AgentConnectionInput(
                    name=patch_data.name or connection.name,
                    type=patch_data.type or connection.type.value,
                    connection=patch_data.connection,
                    backend_validation=(
                        _merge_backend_validation_patch(connection.backend_validation, patch_data.backend_validation)
                        if patch_data.backend_validation is not None
                        else connection.backend_validation
                    ),
                ),
                connection_id=connection.id,
            )
        except (ValidationError, ValueError) as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

        replacement.enabled = connection.enabled if patch_data.enabled is None else patch_data.enabled
        repository.save(replacement)
        return AgentConnectionResponse.from_connection(replacement)

    if patch_data.backend_validation is not None:
        connection.backend_validation = _merge_backend_validation_patch(connection.backend_validation, patch_data.backend_validation)

    if patch_data.name is not None:
        if not patch_data.name.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, 
                detail="Name cannot be empty"
            )
        connection.name = patch_data.name.strip()
        
    if patch_data.enabled is not None:
        connection.enabled = patch_data.enabled
        
    repository.save(connection)
    return AgentConnectionResponse.from_connection(connection)


@router.post("/{connection_id}/evaluate", response_model=EvaluationResult)
def evaluate_connection(connection_id: str, request: EvaluationRequest):
    """
    Run a scenario against a saved agent connection and evaluate the results.
    """
    logger.warning("[VOICE DEBUG 1] evaluate endpoint entered")
    eval_id = request.evaluation_id
    if not eval_id:
        import uuid
        eval_id = f"eval_{uuid.uuid4().hex}"
    from app.log_stream import current_eval_id
    token = current_eval_id.set(eval_id)
    # 1. Load connection
    connection = repository.get(connection_id)
    if not connection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
        
    if not connection.enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Connection is disabled")

    logger.warning("[VOICE DEBUG 2] connection resolved")

    # 2. Load scenario
    scenario_file = Path(request.scenario_path)
    if not scenario_file.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")
        
    try:
        with open(scenario_file, "r") as f:
            scen_data = yaml.safe_load(f)
        scenario = TestScenario(**scen_data)
        scenario = _merge_backend_validation_into_scenario(scenario, connection)
    except Exception as e:
        logger.error(f"Failed to load scenario {request.scenario_path}: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid scenario format: {e}")

    logger.warning("[VOICE DEBUG 3] scenario loaded")

    # 3. Execution
    try:
        logger.warning("[VOICE DEBUG 4] execution started")
        executor = ScenarioExecutor()
        exec_result = executor.execute(connection, scenario)
    except Exception as e:
        logger.error(f"Unexpected error during execution: {e}", exc_info=True)
        # Execution failure is handled by EvaluationService cleanly if it returns a failed ExecutionResult,
        # but if execute() itself completely crashed (e.g., adapter missing from registry), we should wrap it.
        # Actually, ScenarioExecutor wraps errors in a failed ExecutionResult, 
        # so this exception block is just a fail-safe.
        from app.executor import ExecutionResult
        from datetime import datetime, timezone
        exec_result = ExecutionResult(
            success=False,
            connection_id=connection.id,
            agent_type=connection.type.value,
            adapter=connection.adapter,
            error=f"{type(e).__name__}: {str(e) or repr(e)}",
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat()
        )

    # 4. Evaluation
    try:
        logger.warning("[VOICE DEBUG 15] evaluation started")
        eval_service = EvaluationService()
        eval_result = eval_service.evaluate(exec_result, scenario)
        eval_result.evaluation_id = eval_id
        saved = save_evaluation_report(eval_result.model_dump(mode="json"))
        eval_result = eval_result.model_copy(update={"evaluation_id": saved["evaluation_id"]})
        logger.warning("[VOICE DEBUG 16] evaluation completed")
    except Exception as e:
        logger.error(f"Unexpected error during evaluation: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected internal error during evaluation")
        
    logger.warning("[VOICE DEBUG 17] endpoint returning")
    return eval_result
    # current_eval_id.reset(token) handled by end of thread/task


@router.post("/browser-auth/start", response_model=BrowserAuthStartResponse)
async def start_browser_auth(request: BrowserAuthStartRequest):
    try:
        session_id = await browser_auth_manager.start_session(request.url)
        return BrowserAuthStartResponse(session_id=session_id)
    except Exception as e:
        logger.exception("Error starting browser auth")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/browser-auth/save", response_model=BrowserAuthSaveResponse)
async def save_browser_auth(request: BrowserAuthSaveRequest):
    import os
    safe_name = "".join([c if c.isalnum() else "_" for c in request.connection_name]).strip("_")
    if not safe_name:
        safe_name = "default"
    save_path = f"auth-state-{safe_name}.json"

    if not any([request.expected_url, request.authenticated_selector, request.required_cookie]):
        raise HTTPException(
            status_code=422,
            detail="At least one authentication check is required: expected_url, authenticated_selector, or required_cookie",
        )

    result = await browser_auth_manager.save_verified_session(
        request.session_id,
        save_path,
        BrowserAuthCheck(
            expected_url=request.expected_url,
            authenticated_selector=request.authenticated_selector,
            required_cookie=request.required_cookie,
            timeout_seconds=request.timeout_seconds,
        ),
    )
    if not result.session_found:
        raise HTTPException(status_code=404, detail="Session not found or already closed")
    if not result.success:
        if result.storage_state_saved and os.path.exists(save_path):
            os.remove(save_path)
        raise HTTPException(status_code=400, detail=result.error or "Authentication verification failed")

    return BrowserAuthSaveResponse(
        storage_state_path=save_path,
        authentication_detected_before_save=result.authentication_detected_before_save,
        storage_state_saved=result.storage_state_saved,
        fresh_context_restored=result.fresh_context_restored,
        authenticated_ui_detected_after_restore=result.authenticated_ui_detected_after_restore,
    )
