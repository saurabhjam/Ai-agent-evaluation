from __future__ import annotations

from fastapi import FastAPI, HTTPException
from app.log_stream import setup_eval_logger
setup_eval_logger()
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError

import logging
import traceback
import requests
import yaml
from contextlib import asynccontextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

from app.config import settings
from app.orchestrator import run_scenario
from app.schemas import TestRunRequest, TestRunResult
from app.storage import get_run, list_runs
from app.connections.api import router as connections_router
from app.connections.browser_auth import browser_auth_manager
from app.calling.ui_api import router as calling_router
from app.evaluations_api import router as evaluations_router
from app.management.api import router as management_router


@asynccontextmanager
async def _lifespan(app):
    """Start-up / shutdown lifecycle for the FastAPI application."""
    yield
    # Gracefully close any open Playwright browser sessions on shutdown
    try:
        await browser_auth_manager.shutdown()
    except Exception as exc:  # noqa: BLE001
        logger.warning("BrowserAuthManager shutdown error (non-fatal): %s", exc)


app = FastAPI(
    title="Voice Agent & Chatbot Evaluation POC",
    description="Minimal working proof of concept: Ollama-driven simulated user, "
                 "DeepEval + Gemini judge, Pydantic-validated backend.",
    version="0.1.0",
    lifespan=_lifespan,
)

app.include_router(connections_router)
app.include_router(calling_router)
app.include_router(evaluations_router)
app.include_router(management_router)

# ---------------------------------------------------------------------------
# CORS — allow browser requests from any origin (dev/local setup)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Static file serving (CSS, JS) and UI route
# ---------------------------------------------------------------------------
_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR / "static")), name="static")

_ARTIFACTS_DIR = Path(__file__).parent.parent / "artifacts"
_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=str(_ARTIFACTS_DIR)), name="artifacts")


@app.get("/ui", include_in_schema=False)
def serve_ui():
    """Serve the frontend single-page application."""
    return FileResponse(str(_FRONTEND_DIR / "index.html"))


@app.get("/", include_in_schema=False)
def root_redirect():
    """Redirect root to UI."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ui")


# ---------------------------------------------------------------------------
# Scenarios list endpoint — scans the scenarios/ directory for YAML files
# ---------------------------------------------------------------------------
_SCENARIOS_DIR = Path(__file__).parent.parent / "scenarios"


@app.get("/scenarios")
def list_scenarios():
    """
    List available evaluation scenario YAML files.
    Returns id, channel, and relative path for each scenario.
    """
    from app.scenario_catalog import ScenarioCatalog
    catalog = ScenarioCatalog(scenarios_dir=_SCENARIOS_DIR)
    discovered = {entry["path"]: entry for entry in catalog.discovery()}
    results = []
    if not _SCENARIOS_DIR.exists():
        return results
    for yaml_file in sorted(_SCENARIOS_DIR.rglob("*.yaml")):
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            scenario_id = data.get("scenario_id", yaml_file.stem)
            # Determine channel from scenario agent config or file location
            channel = "chatbot"
            agent = data.get("agent", {})
            if isinstance(agent, dict):
                channel = agent.get("channel", "chatbot")
            # voice scenarios may be in a subdirectory named 'voice'
            if "voice" in str(yaml_file.relative_to(_SCENARIOS_DIR)):
                channel = "voice"
            if "calling" in str(yaml_file.relative_to(_SCENARIOS_DIR)):
                channel = "calling"
            relative_path = str(yaml_file.relative_to(Path(__file__).parent.parent)).replace("\\", "/")
            results.append({
                **discovered.get(relative_path, {}),
                "id": scenario_id,
                "channel": channel,
                "path": relative_path,
            })
        except Exception as e:
            logger.warning(f"Could not parse scenario file {yaml_file}: {e}")
    return results


@app.get("/scenarios/catalog")
def get_scenario_catalog():
    from app.scenario_catalog import ScenarioCatalog
    catalog = ScenarioCatalog(scenarios_dir=_SCENARIOS_DIR)
    return {"scenarios": catalog.discovery(), "workflows": [w.model_dump() for w in catalog.workflows.values()], "issues": catalog.issues}



@app.post("/scenarios/validate")
def validate_scenario(payload: dict):
    """Validate scenario YAML without saving."""
    yaml_text = payload.get("yaml_text", "")
    try:
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            raise ValueError("YAML must be a dictionary")
        # Validate against schema
        from app.schemas import TestScenario
        from app.scenario_catalog import ScenarioCatalog
        ScenarioCatalog(scenarios_dir=_SCENARIOS_DIR).resolve(TestScenario(**data))
        return {"status": "ok", "message": "Valid scenario"}
    except ValidationError as e:
        # Return first pydantic error nicely
        err = e.errors()[0]
        field = ".".join(str(loc) for loc in err["loc"])
        msg = err["msg"]
        raise HTTPException(status_code=400, detail=f"Validation failed: {field} {msg}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")

@app.post("/scenarios/save")
def save_scenario(payload: dict):
    """Save scenario YAML to scenarios/ directory."""
    yaml_text = payload.get("yaml_text", "")
    filename = payload.get("filename", "")
    force = payload.get("force", False)
    
    if not filename or not filename.endswith((".yaml", ".yml")):
        raise HTTPException(status_code=400, detail="Filename must end with .yaml or .yml")
        
    # Sanitize filename to prevent path traversal
    import re
    clean_filename = re.sub(r'[^a-zA-Z0-9_\-\.]', '', filename)
    if clean_filename != filename or ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename. Use alphanumeric characters, underscores, and dashes only.")
        
    try:
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            raise ValueError("YAML must be a dictionary")
        from app.schemas import TestScenario
        from app.scenario_catalog import ScenarioCatalog
        catalog = ScenarioCatalog(scenarios_dir=_SCENARIOS_DIR)
        parsed = TestScenario(**data)
        catalog.resolve(parsed, source_path=_SCENARIOS_DIR / clean_filename)
    except ValidationError as e:
        err = e.errors()[0]
        field = ".".join(str(loc) for loc in err["loc"])
        raise HTTPException(status_code=400, detail=f"Validation failed: {field} {err['msg']}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")
        
    target_path = _SCENARIOS_DIR / clean_filename
    if target_path.exists() and not force:
        raise HTTPException(status_code=409, detail="Scenario already exists. Replace it?")
        
    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(yaml_text)
        return {"status": "ok", "message": f"Saved {clean_filename}"}
    except Exception as e:
        logger.error(f"Failed to save scenario: {e}")
        raise HTTPException(status_code=500, detail="Failed to save scenario file")


@app.get("/health")
def health():
    return {"status": "ok"}


class MockChatRequest(BaseModel):
    session_id: str
    message: str
    agent_prompt: str | None = None

class MockChatResponse(BaseModel):
    reply: str

mock_chat_sessions: dict[str, list[dict[str, str]]] = {}

SYSTEM_PROMPT = """You are a helpful customer support agent for an e-commerce company.
Your job is to assist users with their orders.
You can handle:
- damaged order (offer a refund or replacement)
- refund request (process refunds for eligible items)
- order status (provide tracking info)
- cancellation (cancel pending orders)
- human escalation (transfer to a human agent if requested or if you cannot help)

Keep your responses concise, helpful, and directly relevant to the user's message.
Do not make up fake order details unless the user provides them.
If you need an order number, ask for it.
"""

@app.post("/mock-chat", response_model=MockChatResponse)
def mock_chat(request: MockChatRequest):
    """
    Reference AI Chat Agent for testing the evaluation pipeline.
    Maintains session history and uses Ollama.
    """
    if settings.defect_generic_greeting_loop:
        return MockChatResponse(reply="Hello! I am the customer support bot. How can I help you today?")
    
    session_id = request.session_id
    user_message = request.message
    agent_prompt = request.agent_prompt or SYSTEM_PROMPT
    
    if session_id not in mock_chat_sessions:
        mock_chat_sessions[session_id] = [
            {"role": "system", "content": agent_prompt}
        ]
        
    mock_chat_sessions[session_id].append({"role": "user", "content": user_message})

    # Keep a short rolling history to prevent Ollama latency from growing on local CPU.
    history = mock_chat_sessions[session_id]
    messages_payload = [history[0]] + history[1:][-3:]

    try:
        response = requests.post(
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages_payload,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 80}
            },
            timeout=120,
        )
        response.raise_for_status()
        reply = response.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        reply = f"Error generating response: {e}"
        
    mock_chat_sessions[session_id].append({"role": "assistant", "content": reply})
    
    return MockChatResponse(reply=reply)


@app.post("/test-runs", response_model=TestRunResult)
def create_test_run(request: TestRunRequest):
    """
    Validate the scenario (Pydantic does this automatically before this
    function body even runs — malformed personas, out-of-range turn counts,
    etc. are rejected with a 422 here) then execute it end to end.
    """
    try:
        result = run_scenario(request.scenario, agent_override=request.agent_override)
    except Exception as exc:  # noqa: BLE001 — POC-level catch-all, tighten before prod
        logger.error(f"Test run failed:\n{traceback.format_exc()}")
        raise HTTPException(status_code=502, detail=f"Test run failed: {exc}") from exc
    return result


@app.get("/test-runs/{run_id}", response_model=TestRunResult)
def get_test_run(run_id: str):
    result = get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return result


@app.get("/test-runs", response_model=list[TestRunResult])
def get_all_runs(scenario_id: str | None = None):
    return list_runs(scenario_id)
