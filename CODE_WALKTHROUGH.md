# EvalForge — Complete Code Walkthrough & Demo Guide

> **Document purpose:** Live technical walkthrough for a 30–45 minute team demo.
> All claims reference **current code** as of October 2026. Nothing was changed.
> Source of truth is the code, not README or old documentation.

---

## TABLE OF CONTENTS

1. [Project in One Simple Explanation](#part-1-project-in-one-simple-explanation)
2. [Repository Map & Architecture Tree](#part-2-repository-map--architecture-tree)
3. [Top-Level Architecture Diagram](#part-3-top-level-architecture-diagram)
4. [Application Entry Point](#part-4-application-entry-point)
5. [Connection Architecture](#part-5-connection-architecture)
6. [Technologies Used](#part-6-technologies-used)
7. [Chatbot End-to-End Workflow](#part-7-chatbot-end-to-end-workflow)
8. [Scenario / Persona / Simulator](#part-8-scenario--persona--simulator)
9. [User Simulator](#part-9-user-simulator)
10. [Chat Adapters](#part-10-chat-adapters)
11. [REST Adapter Deep Dive](#part-11-rest-adapter-deep-dive)
12. [Authentication](#part-12-authentication)
13. [Browser Token Auth Deep Dive](#part-13-browser-token-auth-deep-dive)
14. [Interactive Chatbot / User Action Engine](#part-14-interactive-chatbot--user-action-engine)
15. [RAG — Concept Explained](#part-15-rag--concept-explained)
16. [RAG Implementation](#part-16-rag-implementation)
17. [How Client Connects RAG](#part-17-how-client-connects-rag)
18. [Client Onboarding Checklist for RAG](#part-18-client-onboarding-checklist-for-rag)
19. [What If Client Has No RAG?](#part-19-what-if-client-has-no-rag)
20. [What If Client Cannot Expose RAG Evidence?](#part-20-what-if-client-cannot-expose-rag-evidence)
21. [RAG Metrics](#part-21-rag-metrics)
22. [Voice Agent](#part-22-voice-agent)
23. [AI Calling Agent](#part-23-ai-calling-agent)
24. [Why Voice and AI Calling Are Different](#part-24-why-voice-and-ai-calling-are-different)
25. [Outbound Calling Flow](#part-25-outbound-calling-flow)
26. [Inbound Calling](#part-26-inbound-calling)
27. [What We Need From Client for AI Calling](#part-27-what-we-need-from-client-for-ai-calling)
28. [What If Client Has No Calling Connection Info?](#part-28-what-if-client-has-no-calling-connection-info)
29. [Calling RAG](#part-29-calling-rag)
30. [Normalization](#part-30-normalization)
31. [Evaluation Engine (DeepEval)](#part-31-evaluation-engine)
32. [Storage / Persistence](#part-32-storage--persistence)
33. [Frontend](#part-33-frontend)
34. [Security](#part-34-security)
35. [Error Handling](#part-35-error-handling)
36. [Implemented vs. Partial vs. Not Implemented](#part-36-implemented-vs-partial-vs-not-implemented)
37. [Test Architecture](#part-37-test-architecture)
38. [Live Walkthrough File Order](#part-38-live-walkthrough-file-order)
39. [Three Demo Scripts](#part-39-three-demo-scripts)
40. [Q&A Preparation](#part-40-qa-preparation)
41. [Technology Summary Table](#part-41-technology-summary-table)
42. [Final Cheat Sheet](#part-42-final-cheat-sheet)

---

## PART 1: PROJECT IN ONE SIMPLE EXPLANATION

### A. 30-Second Explanation

**EvalForge** is a vendor-neutral platform that tests AI agents — chatbots, voice agents, and telephone AI agents — automatically, without a human tester. It creates a simulated user who carries a real conversation with the client's AI agent, then an LLM judge scores the quality of that conversation. It works with any chatbot or AI agent regardless of which company built it.

### B. 2-Minute Explanation

When a company deploys an AI agent, they need to know: *Does it actually solve user problems? Does it stay on topic? Does it hallucinate?* Manual testing is slow, inconsistent, and doesn't scale.

EvalForge solves this by:

1. **Defining a scenario** — a test case in YAML describing who the simulated user is, what they want, and how they behave (persona + goal + tone + edge cases).
2. **Creating a connection** — a saved configuration that tells EvalForge how to reach the client's chatbot (REST endpoint, WebSocket, browser-driven, etc.) including authentication.
3. **Running the conversation** — an AI-powered simulated user (running on Groq/Llama) drives a real conversation with the client's actual deployed chatbot. No scripts, no fake responses.
4. **Scoring the results** — DeepEval (backed by Groq/Gemini as the judge model) measures: Did the agent meet the user's goal? Was the tone right? If the agent uses RAG, was its answer faithful to what it retrieved?
5. **Reporting** — Results, transcript, and scores appear in the web UI.

This applies to **any** chatbot, **any** voice agent, and **any** AI telephone agent. The platform is explicitly designed NOT to be tied to a single vendor.

### C. Technical Explanation

EvalForge is a FastAPI backend + vanilla JS/HTML/CSS frontend. The backend exposes:
- A **Connection system** (`app/connections/`) that stores adapter configurations in SQLite and routes each evaluation to the correct adapter
- A **Scenario system** (YAML files + `app/schemas.py`) that defines test personas and goals
- A **ScenarioExecutor** (`app/executor.py`) that runs chatbot or voice conversations using a pluggable adapter pattern
- A **User Simulator** (`app/simulator.py`) powered by Groq's Llama model that generates realistic user turns
- An **Evaluation Service** (`app/evaluation_service.py` + `app/evaluator.py`) that runs DeepEval metrics using a Groq judge (with Gemini fallback)
- A **Calling subsystem** (`app/calling/`) with provider-neutral models for phone/SIP calling evaluation
- A **Voice subsystem** (`app/voice/`) for real-time audio sessions
- A **RAG integration** (`app/rag.py`) that extracts retrieval evidence from API responses and evaluates answer faithfulness

---

## PART 2: REPOSITORY MAP & ARCHITECTURE TREE

```
evalution-ai-agent/
|
+-- app/                          <- BACKEND (FastAPI application)
|   +-- main.py                   * CRITICAL -- Application entry point, router registration
|   +-- config.py                 * CRITICAL -- All settings (API keys, models, limits)
|   +-- schemas.py                * CRITICAL -- Pydantic models: Persona, TestScenario, MetricResult, TestRunResult
|   +-- orchestrator.py           * CRITICAL -- Legacy run_scenario() used by /test-runs endpoint
|   +-- executor.py               * CRITICAL -- ScenarioExecutor (chatbot + voice dispatch)
|   +-- simulator.py              * CRITICAL -- Groq-powered simulated user turn generator
|   +-- evaluation_service.py     * CRITICAL -- EvaluationService: ties executor -> evaluator -> scoring
|   +-- evaluator.py              * CRITICAL -- DeepEval metrics (GEval, Hallucination, Faithfulness, etc.)
|   +-- rag.py                    * CRITICAL -- RAG evidence extraction via dot-path traversal
|   +-- storage.py                  IMPORTANT -- SQLite save/get/list for test run results
|   |
|   +-- models/                   * CRITICAL -- Shared conversation models
|   |   +-- conversation.py       * RAGEvidence, ConversationMessage, NormalizedConversation
|   |   +-- connection.py         * AgentConnection (universal connection descriptor)
|   |   +-- voice.py              * VoiceConversation, VoiceTurn, Speaker
|   |
|   +-- connections/              * CRITICAL -- Universal Connection System
|   |   +-- api.py                * Connection REST API (create/test/list/edit/delete/evaluate/browser-auth)
|   |   +-- manager.py            * ConnectionManager (routes to adapter registry)
|   |   +-- registry.py           * AdapterRegistry (registers all adapters by type+name)
|   |   +-- storage.py            * ConnectionRepository (SQLite persistence for connections)
|   |   +-- browser_auth.py       * BrowserAuthManager (Playwright login session capture)
|   |   +-- parser.py               IMPORTANT -- Parses AgentConnectionInput -> AgentConnection
|   |   +-- input.py                IMPORTANT -- AgentConnectionInput Pydantic model
|   |   +-- result.py               IMPORTANT -- ConnectionTestResult model
|   |
|   +-- adapters/                 * CRITICAL -- Transport adapters
|   |   +-- factory.py            * Legacy AdapterFactory (used by orchestrator.py)
|   |   +-- chat/                 * Chatbot adapters
|   |       +-- base.py           * ChatAdapter abstract base, capabilities, exceptions
|   |       +-- rest.py           * CRITICAL -- RestChatAdapter (legacy + multi-step + RAG + browser-token)
|   |       +-- websocket.py        IMPORTANT -- WebSocketChatAdapter (partial -- scripted responses only)
|   |       +-- browser.py          IMPORTANT -- BrowserChatAdapter (Playwright-driven full browser)
|   |       +-- fake.py             TEST/DEV -- FakeChatAdapter (always returns fixed reply)
|   |
|   +-- interactive/              * IMPORTANT -- User Action Engine (UI interaction planner)
|   |   +-- orchestrator.py       * ConversationOrchestrator (runs turns with action engine)
|   |   +-- decision_planner.py   * DefaultDecisionPlanner (maps components -> interaction plan)
|   |   +-- response_understanding.py  Detects chatbot components (buttons, dropdowns, forms...)
|   |   +-- action_executor.py    * ActionExecutor (executes planned interactions via adapter)
|   |   +-- component_types.py      Component type enum
|   |   +-- interaction_types.py    Interaction type enum
|   |   +-- interaction_models.py   Interaction pydantic model
|   |   +-- interaction_plan.py     InteractionPlan model
|   |   +-- form_engine.py          Form step orchestration
|   |   +-- workflow_engine.py      Workflow orchestration
|   |
|   +-- voice/                    * IMPORTANT -- Voice evaluation
|   |   +-- converter.py          * voice_to_normalized_conversation() -- key normalization
|   |   +-- persona.py            * VoicePersonaEngine (runs automated voice session)
|   |   +-- runner.py               VoiceRunner
|   |   +-- metrics.py            * Voice-specific metrics (latency, interruption, etc.)
|   |
|   +-- calling/                  * CRITICAL -- AI Calling Agent evaluation
|   |   +-- models.py             * CallSession, CallStatus, CallDirection, CallTranscriptTurn
|   |   +-- normalizer.py         * call_transcript_to_normalized_conversation()
|   |   +-- runner.py             * CallingEvaluationRunner (mock call simulation)
|   |   +-- ui_api.py             * CRITICAL -- All /calling/* HTTP endpoints
|   |   +-- evaluation_bridge.py  * CallingEvaluationBridge -> EvaluationService
|   |   +-- evaluation_runner.py  * CallingEvaluationRuntimeRunner
|   |   +-- provider_adapter.py   * CallProviderAdapter (abstract base)
|   |   +-- provider_resolver.py  * ProviderResolver (selects provider by config)
|   |   +-- lifecycle.py          * CallLifecycleManager (state machine transitions)
|   |   +-- providers/
|   |       +-- base.py           * Base provider
|   |       +-- mock.py           * MockCallProvider (fully in-memory, always works)
|   |       +-- twilio.py         * TwilioProvider (real API calls -- requires credentials)
|   |       +-- whisper.py        * WhisperProvider (local transcription)
|   |
|   +-- adapters/voice/           (voice transport adapters)
|       +-- livekit.py            LiveKitVoiceAdapter
|       +-- fake.py               FakeVoiceAdapter
|       +-- local.py              LocalVoiceAdapter
|
+-- scenarios/                    * CRITICAL -- YAML test scenario library
|   +-- refund_request.yaml       * Representative chatbot scenario (show in demo)
|   +-- gemini_customer_refund.yaml
|   +-- real_company_chat.yaml
|   +-- sophia_property_maintenance.yaml
|   +-- querywing_return_request.yaml
|   +-- voice/                    Voice-channel scenarios
|       +-- refund_request.yaml
|       +-- refund_request_livekit.yaml
|
+-- frontend/                     * IMPORTANT -- Single-page web UI
|   +-- index.html                * Dashboard, connections, evaluations, calling UI
|   +-- static/
|       +-- app.js                * All frontend logic
|       +-- styles.css
|
+-- tests/                        TEST/DEV -- Pytest test suite (50+ test files)
|
+-- requirements.txt              * Dependencies
+-- .env.example                  * Environment variable template
+-- eval_results.db               SQLite -- evaluation run results
+-- connections.db                SQLite -- agent connections
+-- calling_connections.json      JSON -- calling connections storage
+-- auth-state-*.json             Browser storage state files (captured login sessions)
```

### Directory Purposes

| Directory | Contains | Why It Exists | Who Calls It | Calls Next |
|-----------|----------|---------------|--------------|------------|
| `app/connections/` | Connection CRUD + test + browser-auth | Persist and validate how EvalForge reaches each client agent | `app/main.py` (router include) | `app/connections/registry.py` -> adapter |
| `app/adapters/chat/` | REST, WebSocket, Browser, Fake adapters | Each chatbot has different transport -- adapters unify the interface | `ScenarioExecutor`, `ConnectionManager` | Client chatbot API |
| `app/interactive/` | Action engine, decision planner, form engine | Some chatbots return buttons/dropdowns/forms -- needs automated interaction | `ScenarioExecutor` (when `enable_user_action_engine=True`) | ChatAdapter methods |
| `app/calling/` | Call lifecycle, providers, normalizer, bridge | Phone/SIP agents have different evidence model than chatbots | `calling/ui_api.py` (router) | `EvaluationService` |
| `app/voice/` | Voice session, STT/TTS, persona engine, converter | Real-time audio requires separate session management | `ScenarioExecutor._execute_voice()` | `evaluate_transcript()` |
| `scenarios/` | YAML test scenario files | External configuration for test runs -- no code change needed for new tests | `main.py /scenarios` endpoint | `TestScenario` Pydantic model |
| `frontend/` | index.html + app.js + styles.css | Web UI for non-engineers to manage connections and view results | Browser | `/connections`, `/calling`, `/scenarios` APIs |

---

## PART 3: TOP-LEVEL ARCHITECTURE DIAGRAM

```
+------------------------------------------------------------+
|                    Browser / Client UI                      |
|              frontend/index.html + app.js                   |
+---------------------------+--------------------------------+
                            | HTTP (REST)
                            v
+------------------------------------------------------------+
|                    FastAPI App Layer                         |
|                     app/main.py                             |
|  Routes:                                                    |
|   /connections  -> connections/api.py (router)              |
|   /calling      -> calling/ui_api.py (router)               |
|   /test-runs    -> orchestrator.py:run_scenario()           |
|   /scenarios    -> main.py (inline)                         |
+-------+------------------+--------------------------------+
        |                  |
        v                  v
+---------------+  +-------------------+
| Connections   |  |  Calling API       |
| api.py        |  |  calling/ui_api.py |
| (CRUD+eval)   |  |  (CRUD+run)        |
+-------+-------+  +--------+----------+
        |                   |
        | load connection    | load connection + scenario
        v                   v
+------------------+  +-----------------------------+
| ScenarioExecutor |  | CallingEvaluationRuntimeRunner|
| app/executor.py  |  | calling/evaluation_runner.py  |
+------+-----------+  +-----------+-----------------+
       |                          |
       | create adapter           | resolve provider
       v                          v
+--------------------------+  +--------------------+
|    ConnectionManager     |  |   ProviderResolver  |
|    connections/manager   |  |   calling/provider  |
|         v                |  |   _resolver.py      |
|    AdapterRegistry       |  +--------+-----------+
|    connections/registry  |           |
|         v                |           v
|  RestChatAdapter         |  +--------------------+
|  WebSocketChatAdapter    |  |  MockCallProvider OR|
|  BrowserChatAdapter      |  |  TwilioProvider     |
|  FakeVoiceAdapter        |  |  calling/providers/ |
|  LiveKitVoiceAdapter     |  +--------+-----------+
+---------+----------------+           |
          |                            |
          | Simulated user turns       | Simulated call lifecycle
          v                            v
+--------------------------+  +--------------------+
|    generate_next_user_   |  |  build_mock_        |
|    turn() -- Groq/Llama  |  |  transcript()       |
|    app/simulator.py      |  |  calling/runner.py  |
+----------+---------------+  +--------+-----------+
           |                           |
           v                           v
+--------------------------------------------------+
|         NormalizedConversation                    |
|         app/models/conversation.py               |
|  [ConversationMessage(role, content, rag_evidence)]|
+-------------------+--------------+---------------+
                    |
                    v
+--------------------------------------------------+
|              EvaluationService                    |
|              app/evaluation_service.py            |
|  1. _rag_evidence_by_turn()                       |
|  2. evaluate_transcript()  ->  evaluator.py       |
|  3. _balanced_overall_score()                     |
+-------------------+------------------------------+
                    |
                    v
+--------------------------------------------------+
|              evaluate_transcript()                |
|              app/evaluator.py                     |
|  DeepEval: GEval, ConversationalGEval,            |
|            HallucinationMetric, FaithfulnessMetric|
|            AnswerRelevancyMetric                  |
|  Judge: GroqJudge (primary) -> GeminiJudge (fb)  |
+-------------------+------------------------------+
                    |
                    v
+--------------------------------------------------+
|     EvaluationResult / TestRunResult              |
|     saved to SQLite (app/storage.py)              |
|     returned to frontend as JSON                  |
+--------------------------------------------------+
```

### Arrow Source -> Destination Reference

| Arrow | Source File / Function | Destination File / Function |
|-------|----------------------|---------------------------|
| UI -> API | `frontend/app.js` fetch calls | `app/main.py` FastAPI routes |
| API -> Evaluate | `connections/api.py:evaluate_connection()` | `executor.py:ScenarioExecutor.execute()` |
| Executor -> Adapter | `executor.py:_execute_chatbot()` | `connections/registry.py:AdapterRegistry.create()` |
| Executor -> Simulator | `executor.py:_execute_chatbot()` | `simulator.py:generate_next_user_turn()` |
| Simulator -> LLM | `simulator.py:generate_next_user_turn()` | Groq API (cloud) |
| Adapter -> Conversation | `rest.py:send_message()` | `models/conversation.py:ConversationMessage` |
| Executor -> EvalService | `connections/api.py:evaluate_connection()` | `evaluation_service.py:EvaluationService.evaluate()` |
| EvalService -> Evaluator | `evaluation_service.py:evaluate()` | `evaluator.py:evaluate_transcript()` |
| Evaluator -> DeepEval | `evaluator.py:evaluate_transcript()` | `deepeval` library |
| EvalService -> Storage | via `orchestrator.py:run_scenario()` | `storage.py:save_run()` |
| Calling -> Bridge | `calling/ui_api.py:run_calling_evaluation()` | `calling/evaluation_bridge.py:CallingEvaluationBridge.evaluate()` |
| Bridge -> EvalService | `calling/evaluation_bridge.py:evaluate()` | `evaluation_service.py:EvaluationService.evaluate()` |

---

## PART 4: APPLICATION ENTRY POINT

**File:** `app/main.py`

### How FastAPI Starts

```python
# app/main.py line 38-44
app = FastAPI(title="Voice Agent & Chatbot Evaluation POC", ...)
app.include_router(connections_router)   # /connections/*
app.include_router(calling_router)       # /calling/*
```

The app is started with Uvicorn:
```
uvicorn app.main:app --reload
```

**Lifecycle:** `@asynccontextmanager _lifespan()` (line 27-35) handles graceful shutdown of the `BrowserAuthManager` when the server stops -- closing any open Playwright browser windows.

**CORS:** All origins allowed (line 52-57) -- development setup only.

**Static files:** `frontend/static/` served at `/static`, `index.html` served at `/ui`.

### Router Registration

| Router | Prefix | File |
|--------|--------|------|
| Connections | `/connections` | `app/connections/api.py` |
| Calling | `/calling` | `app/calling/ui_api.py` |
| Inline | `/test-runs`, `/scenarios`, `/health`, `/mock-chat` | `app/main.py` |

### Important Routes Table

| Method | Route | File | Function | Purpose |
|--------|-------|------|----------|---------|
| GET | `/ui` | main.py | `serve_ui()` | Serves the SPA |
| GET | `/scenarios` | main.py | `list_scenarios()` | Lists scenario YAML files |
| POST | `/scenarios/validate` | main.py | `validate_scenario()` | Validates YAML without saving |
| POST | `/scenarios/save` | main.py | `save_scenario()` | Saves a scenario YAML |
| POST | `/test-runs` | main.py | `create_test_run()` | Legacy: run scenario inline (no saved connection) |
| GET | `/test-runs/{id}` | main.py | `get_test_run()` | Get one evaluation result |
| GET | `/test-runs` | main.py | `get_all_runs()` | List all evaluation results |
| POST | `/mock-chat` | main.py | `mock_chat()` | Built-in reference Ollama chatbot |
| POST | `/connections` | connections/api.py | `create_connection()` | Save new connection |
| POST | `/connections/{id}/test` | connections/api.py | `test_connection_endpoint()` | Test connectivity |
| POST | `/connections/{id}/evaluate` | connections/api.py | `evaluate_connection()` | **RUN EVALUATION** |
| PATCH | `/connections/{id}` | connections/api.py | `update_connection()` | Edit connection |
| POST | `/connections/browser-auth/start` | connections/api.py | `start_browser_auth()` | Open visible browser for login |
| POST | `/connections/browser-auth/save` | connections/api.py | `save_browser_auth()` | Save authenticated browser state |
| GET | `/calling/providers` | calling/ui_api.py | `list_calling_providers()` | Provider options |
| POST | `/calling/connections` | calling/ui_api.py | `create_calling_connection()` | Save calling config |
| POST | `/calling/connections/{id}/run` | calling/ui_api.py | `run_calling_evaluation()` | **RUN CALLING EVAL** |

### Top 7 APIs for Walkthrough

1. `POST /connections` -- how a client is onboarded
2. `POST /connections/{id}/test` -- validate connectivity
3. `POST /connections/{id}/evaluate` -- the main evaluation flow
4. `POST /connections/browser-auth/start` + `save` -- browser token auth flow
5. `GET /scenarios` -- how scenarios are discovered
6. `POST /calling/connections/{id}/run` -- AI calling evaluation
7. `GET /test-runs` -- view all results

---

## PART 5: CONNECTION ARCHITECTURE

### What a Connection Is

A connection is the saved configuration that tells EvalForge how to reach a client's AI agent. It is stored as an `AgentConnection` object (`app/models/connection.py`).

```python
class AgentConnection(BaseModel):
    id: str          # Stable unique identifier
    name: str        # Human label (e.g., "Acme Support Chatbot")
    type: AgentType  # "chatbot" or "voice"
    adapter: str     # "rest" | "websocket" | "browser" | "livekit" | etc.
    config: dict     # All adapter-specific config (URL, auth, mappings)
    enabled: bool    # Whether available for runs
```

**Key Design:** The `config` dict is deliberately free-form. All vendor-specific details, URLs, headers, auth, request/response field mappings, and RAG configuration live inside `config`. The `AgentConnection` model itself never changes when a new adapter is added.

### Connection Lifecycle

```
POST /connections
        |
        v
AgentConnectionInput  (connections/input.py)
        |
        v  parse_connection_input()  (connections/parser.py)
        |
        v
AgentConnection  (models/connection.py)
        |
        v  repository.save()  (connections/storage.py)
        |
        v  SQLite agent_connections table (connections.db)
```

```
POST /connections/{id}/evaluate
        |
        v  repository.get()
        |
        v  ConnectionManager.create_adapter()
        |
        v  AdapterRegistry.create()  (connections/registry.py)
        |    lazy-imports adapter class
        v
Concrete adapter instance (RestChatAdapter, etc.)
        |
        v  adapter.connect()
        |
Client chatbot API
```

### What Data Is Stored in a Connection

**Example REST connection config:**
```json
{
  "base_url": "https://api.client.com",
  "send": { "path": "/chat/send", "method": "POST" },
  "receive": { "path": "/chat/messages", "polling": {"interval_ms": 500, "timeout_seconds": 30} },
  "auth": { "type": "bearer", "value": "env:CHATBOT_API_KEY" },
  "request_mapping": { "message_field": "content" },
  "response_mapping": { "text_path": "messages[0].text" },
  "rag_config": { "context_path": "retrieved_chunks[].content" }
}
```

### Secret Handling

- Auth values starting with `env:` are resolved at runtime from environment variables: `"value": "env:MY_API_KEY"` -> `os.environ.get("MY_API_KEY")` (see `rest.py` line 295-298)
- `AgentConnectionResponse.from_connection()` in `connections/api.py` (line 93-102) calls `_safe_connection_config()` which blanks `auth.value` and `rag_config.evidence_request.auth.value` before returning to the API consumer
- `AgentConnection.__repr__` (line 164-173) deliberately omits the `config` dict so credentials never appear in logs
- `_sanitise_error_message()` in `connections/manager.py` (line 287-303) redacts `key=`, `secret=`, `token=`, `password=` patterns from error messages

### Add / Edit / Test / Evaluate Difference

| Action | Endpoint | What Happens |
|--------|----------|-------------|
| **Add Connection** | `POST /connections` | Parses input, saves AgentConnection to SQLite |
| **Edit Connection** | `PATCH /connections/{id}` | Replaces saved connection, re-validates |
| **Test Connection** | `POST /connections/{id}/test` | Instantiates adapter, calls `adapter.connect()`, returns pass/fail |
| **Run Evaluation** | `POST /connections/{id}/evaluate` | Full flow: load connection + scenario -> executor -> simulator -> adapter -> evaluator -> result |

---

## PART 6: TECHNOLOGIES USED

| Technology | Where Used | Why Used |
|-----------|-----------|---------|
| **Python 3.11/3.12** | Entire backend | Primary language |
| **FastAPI 0.115** | `app/main.py`, all API files | Async-capable REST API with automatic OpenAPI/Pydantic validation |
| **Pydantic v2** | `app/schemas.py`, `app/models/`, everywhere | Strict data validation, serialization, settings management |
| **pydantic-settings** | `app/config.py` | Read settings from `.env` into `Settings` dataclass |
| **requests** | `app/adapters/chat/rest.py`, `app/orchestrator.py` | Sync HTTP calls to client chatbot endpoints |
| **Playwright (async)** | `app/connections/browser_auth.py`, `app/adapters/chat/browser.py` | Browser automation: login session capture + browser-driven chatbot interaction |
| **DeepEval 2.0.9** | `app/evaluator.py` | LLM evaluation framework: GEval, HallucinationMetric, FaithfulnessMetric, AnswerRelevancyMetric, ConversationalGEval |
| **google-generativeai** | `app/evaluator.py:GeminiJudge` | Gemini 2.0-flash as fallback judge model |
| **Groq** | `app/simulator.py`, `app/evaluator.py:GroqJudge` | Primary simulator model (llama-3.1-8b) + primary judge model |
| **Ollama** | `app/main.py:/mock-chat` | Local mock chatbot endpoint for testing the evaluation pipeline |
| **SQLite** | `app/storage.py`, `app/connections/storage.py` | Simple file-based persistence for connections + eval results |
| **PyYAML** | `app/main.py`, `app/connections/api.py` | YAML scenario file parsing |
| **python-dotenv** | `app/config.py` | Load `.env` file at startup |
| **sounddevice + numpy** | `app/voice/audio.py` | Local microphone capture for voice sessions |
| **faster-whisper** | `app/calling/providers/whisper.py` | Local STT transcription for call recordings |
| **piper-tts** | Voice subsystem | Local TTS for voice session |
| **uvicorn[standard]** | Server | ASGI server (includes WebSocket support) |
| **JSON (stdlib)** | `app/calling/ui_api.py` | Calling connections stored as flat JSON file |
| **HTML/CSS/JS (vanilla)** | `frontend/` | SPA UI -- no framework dependency |

---

## PART 7: CHATBOT END-TO-END WORKFLOW

### Complete Code Path: "User Clicks Run Evaluation"

**User action in browser:** Selects a connection + scenario, clicks "Run Evaluation"

```
Step 1 -- Frontend sends request
File:     frontend/app.js
Action:   fetch('POST /connections/{id}/evaluate', { scenario_path })
Output:   HTTP request to backend
```

```
Step 2 -- API endpoint receives it
File:     app/connections/api.py  line 261-326
Function: evaluate_connection(connection_id, request)
Input:    connection_id (str), request.scenario_path (str)
Action:   Loads connection from SQLite via repository.get()
Output:   AgentConnection object
```

```
Step 3 -- Load scenario from YAML
File:     app/connections/api.py  line 277-288
Function: evaluate_connection() (continued)
Input:    request.scenario_path (relative path)
Action:   yaml.safe_load() -> TestScenario(**scen_data)
Output:   TestScenario with persona, max_turns, pass_threshold, rag_context
```

```
Step 4 -- Execute scenario
File:     app/executor.py  line 60-265
Function: ScenarioExecutor.execute(connection, scenario)
Input:    AgentConnection, TestScenario
Action:   deep-merges scenario.agent.config into connection.config
          calls ConnectionManager.create_adapter(merged_connection)
Output:   ExecutionResult (with transcript)
```

```
Step 5 -- Select & instantiate adapter
File:     app/connections/registry.py  line 184-191
Function: AdapterRegistry.create(connection)
Input:    AgentConnection (type="chatbot", adapter="rest")
Action:   lazy-imports RestChatAdapter, calls RestChatAdapter(config)
Output:   RestChatAdapter instance
```

```
Step 6 -- Connect to chatbot
File:     app/adapters/chat/rest.py  line 537-558
Function: RestChatAdapter.connect()
Input:    adapter config
Action:   If multi-step: POST to session endpoint to get remote session token
          If legacy: no-op
Output:   Session established
```

```
Step 7 -- Conversation loop (up to max_turns)
File:     app/executor.py  line 231-264
Function: ScenarioExecutor._execute_chatbot()
Loop:     for _ in range(scenario.max_turns):
```

```
Step 8 -- Generate simulated user message
File:     app/simulator.py  line 65-129
Function: generate_next_user_turn(persona, transcript)
Input:    Persona (name/goal/tone/edge_case), current transcript
Action:   Builds system prompt with persona, sends to Groq llama-3.1-8b
          Groq returns: next user message
Output:   { "message": "I'd like a refund for order #A1029", "attachments": [] }
```

```
Step 9 -- Send to chatbot
File:     app/adapters/chat/rest.py  line 591-747
Function: RestChatAdapter.send_message(user_message)
Input:    user message string
Action:   Appends simulated_user ConversationMessage to transcript
          POSTs to client chatbot endpoint with configured request mapping
          (Legacy) or POSTs to send endpoint + polls receive endpoint (multi-step)
          Receives chatbot reply
          Extracts RAG evidence if rag_config present
          Appends agent ConversationMessage (with rag_evidence) to transcript
Output:   agent reply string
```

```
Step 10 -- Check stopping condition
File:     app/executor.py  line 243-244
Code:     if END_TOKEN in user_message or not user_message: break
          (Groq returns "[END_CONVERSATION]" when goal is satisfied)
```

```
Step 11 -- Get normalized conversation
File:     app/adapters/chat/rest.py  -- get_conversation()
Function: adapter.get_conversation()
Output:   NormalizedConversation with list[ConversationMessage]
```

```
Step 12 -- EvaluationService receives result
File:     app/evaluation_service.py  line 82-208
Function: EvaluationService.evaluate(exec_result, scenario)
Input:    ExecutionResult (transcript), TestScenario
Action:   _rag_evidence_by_turn() -- extracts any rag_evidence from each agent turn
          _resolve_rag_status() -- determines if RAG will be evaluated
          evaluate_transcript() -- runs DeepEval metrics
Output:   EvaluationResult
```

```
Step 13 -- DeepEval metrics
File:     app/evaluator.py  line 250-388
Function: evaluate_transcript(persona, transcript, rag_context, rag_evidence_by_turn)
Action:   Builds LLMTestCase and ConversationalTestCase
          Runs: GEval (Goal Completion), GEval (Tone), ConversationalGEval (Quality)
          If RAG evidence available: HallucinationMetric, FaithfulnessMetric, AnswerRelevancyMetric
          Each metric calls GroqJudge.generate() -> Groq API
Output:   list[MetricResult]
```

```
Step 14 -- Score aggregation
File:     app/evaluation_service.py  line 330-340
Function: _balanced_overall_score(metrics)
Action:   Average of (avg base metrics, avg RAG metrics)
          Compared to scenario.pass_threshold (default 0.7)
Output:   overall_score (float), passed (bool)
```

```
Step 15 -- Return to frontend
File:     app/connections/api.py  line 326
Function: return eval_result
Action:   JSON serialized EvaluationResult -> frontend
          frontend renders transcript, scores, metrics table
```

---

## PART 8: SCENARIO / PERSONA / SIMULATOR

### Scenario YAML Structure

**File:** `scenarios/refund_request.yaml`

```yaml
scenario_id: refund_request_v1      # Unique ID for this scenario

agent:
  channel: chatbot                  # "chatbot" or "voice"
  adapter: fake                     # Which adapter to use (overridden by connection)

persona:
  name: "Priya"                     # Simulated user's name
  goal: "Get a refund for an order that arrived damaged, order #A1029"
  tone: "polite but increasingly impatient if the agent stalls"
  edge_case: "mentions the order number only if asked directly"

max_turns: 6                        # Stop after 6 turns maximum
pass_threshold: 0.7                 # Score >= 0.7 = PASS

rag_context:                        # Reference context for faithfulness checking
  - "Refund policy: orders damaged in transit are eligible for a full refund..."

agent_prompt: |                     # System prompt for the reference mock chatbot
  You are a helpful customer support agent...
```

### Pydantic Model

**File:** `app/schemas.py`

```python
class Persona(BaseModel):
    name: str           # Validated: 2-60 chars
    goal: str           # Validated: 10-400 chars, not blank/n/a
    tone: str           # Validated: 3-60 chars
    edge_case: Optional[str]  # Optional adversarial behavior

class TestScenario(BaseModel):
    scenario_id: str
    agent: AgentConfig        # channel + adapter + config
    persona: Persona
    steps: Optional[list]     # Optional explicit step-by-step actions
    max_turns: int            # Default 6, enforced min/max from Settings
    pass_threshold: float     # Default 0.7
    rag_context: Optional[list[str]]  # Reference context for RAG checks
    agent_prompt: Optional[str]
```

### Scenario -> Evaluation Flow

```
scenarios/*.yaml
      |
      v  yaml.safe_load() + TestScenario(**data)
      |  app/main.py or connections/api.py
      |
      v  ScenarioExecutor.execute(connection, scenario)
      |  app/executor.py
      |
      v  generate_next_user_turn(scenario.persona, transcript)
      |  app/simulator.py
      |
      v  evaluate_transcript(persona, transcript, rag_context)
         app/evaluator.py
```

---

## PART 9: USER SIMULATOR

**File:** `app/simulator.py`

The simulated user is **not scripted**. EvalForge does NOT pre-write user messages. Instead, an LLM plays the role of the user defined by the persona.

### How It Works

```python
# app/simulator.py line 21-33 -- System Prompt Template
SYSTEM_TEMPLATE = """You are role-playing as a user talking to a customer support agent.
Persona name: {name}
Your goal: {goal}
Your tone: {tone}
{edge_case_line}

Rules:
- Speak ONLY as the user, in first person. Never break character.
- Never reveal you are an AI or that this is a test.
- Keep each message short and natural (1-3 sentences).
- If the agent has fully satisfied your goal, respond with exactly: [END_CONVERSATION]
- Otherwise, react naturally and push toward your goal.
"""
```

### Provider: Groq

```python
# app/simulator.py line 71-80
client = Groq(api_key=settings.groq_api_key)
response = client.chat.completions.create(
    model=settings.groq_model,          # "llama-3.1-8b-instant"
    messages=messages,                   # System + conversation history
    temperature=0.5,
    max_completion_tokens=256,
    reasoning_effort="low",
    timeout=10.0
)
```

### Conversation History

The full conversation transcript (all prior user and agent turns) is appended to the prompt. The LLM has context of everything said so far and generates the next realistic user message.

### Stopping Behavior

When the simulated user's goal is fully satisfied, Groq returns `[END_CONVERSATION]`. The executor checks for this token:
```python
# app/executor.py line 243-244
if END_TOKEN in user_message or not user_message:
    break
```

### Attachment Support

If the persona's goal or edge case references `[ATTACHMENT: path/to/file]`, the simulator extracts these and passes them to `adapter.send_message(attachments=[...])`. Deduplication prevents the same attachment from being sent more than intended.

---

## PART 10: CHAT ADAPTERS

### Overview

All chat adapters implement `ChatAdapter` (abstract base in `app/adapters/chat/base.py`) with a standard interface:
- `connect()` -- establish session
- `send_message(message, agent_prompt, attachments)` -- send user turn, get agent reply
- `get_transcript()` -- get current transcript list
- `get_conversation()` -- get `NormalizedConversation`
- `close()` -- cleanup

### Adapter Comparison Table

| Adapter | File | When Used | Real Connection? | RAG Support | Interactive | Attachments |
|---------|------|-----------|-----------------|-------------|-------------|-------------|
| **REST** | `adapters/chat/rest.py` | Client has HTTP API | Full | Full (same-response + separate API) | Via steps | Yes (multi-step multipart) |
| **WebSocket** | `adapters/chat/websocket.py` | Client uses WS | Scripted only (connect() stub) | Partial (response parsing) | No | No |
| **Browser** | `adapters/chat/browser.py` | Client has web UI only | Full (Playwright) | No (no API response to parse) | Yes (click, type, select) | Yes (file upload) |
| **Fake** | `adapters/chat/fake.py` | Testing / CI | N/A (in-memory) | No | No | No |

### REST Adapter -- Config Required

```json
{
  "endpoint": "https://api.client.com/chat",
  "method": "POST",
  "auth": { "type": "bearer", "value": "env:API_KEY" },
  "request_mapping": { "message_field": "query" },
  "response_mapping": { "text_path": "response.text" }
}
```

OR multi-step:
```json
{
  "base_url": "https://api.client.com",
  "send": { "path": "/messages", "method": "POST" },
  "receive": { "path": "/messages", "polling": { "interval_ms": 500, "timeout_seconds": 30 }, "text_field": "body" }
}
```

### Browser Adapter -- Config Required

```json
{
  "url": "https://client.com/chat",
  "storage_state": "auth-state-ClientName.json",
  "chat_input_selector": "#chat-input",
  "send_button_selector": "#send-btn",
  "message_selector": ".bot-message"
}
```

---

## PART 11: REST ADAPTER DEEP DIVE

**File:** `app/adapters/chat/rest.py` -- `RestChatAdapter` class

### Initialization Order

1. **Config extraction** (line 254-266): Reads `base_url`, `endpoint`, `send`, `receive` from config. Sets `is_multi_step = bool(send_config and receive_config)`.
2. **Header resolution** (line 271-281): Static headers, resolves `env:` values.
3. **Auth resolution** (line 283-314): Dispatches to:
   - `_resolve_browser_token()` -- calls `browser_auth_manager.extract_browser_token_sync()`
   - `_resolve_dynamic_rest()` -- multi-step token fetch
   - `bearer` / `api_key` -- sets `Authorization` header directly
4. **Request/response mapping** (line 317-330): Reads `request_mapping.message_field`, `response_mapping.text_path`.

### Two Operating Modes

**Legacy (single-request) mode** -- `endpoint` key present:
```python
# rest.py line 749-890 -- _send_message_legacy()
# Builds request payload using request_mapping
# POSTs to endpoint
# Reads response using response_mapping.text_path
# Extracts rag_evidence if configured
# Appends ConversationMessage(role="agent", rag_evidence=...)
```

**Multi-step mode** -- `send` + `receive` keys present:
```python
# rest.py line 625-747 -- _send_message_multi_step()
# 1. Get baseline AI message count (receive endpoint)
# 2. POST user message to send endpoint
# 3. Poll receive endpoint until count increases
# 4. Read new message, extract RAG evidence
# 5. Append ConversationMessage
```

### RAG Evidence Extraction

```python
# rest.py line 435-446 -- _extract_rag_evidence_for_response()
rag_config = self.config.get("rag_config") or {}
mode = rag_config.get("mode")
if mode == "separate_api":
    return self._fetch_rag_evidence_from_api(response_data, rag_config)
return extract_rag_evidence(response_data, self.config)  # Same-response mode
```

### Interactive Metadata

The REST adapter extracts `components`, `buttons`, `quick_replies`, `dropdowns`, `forms`, etc. from responses via `_extract_response_components()` (line 164-237) and stores them in `ConversationMessage.metadata["components"]`. The interactive engine uses these when enabled.

---

## PART 12: AUTHENTICATION

**File:** `app/adapters/chat/rest.py` -- `__init__()` line 283-314

### Supported Auth Modes

| Mode | `auth.type` | What Client Provides | How EvalForge Uses It |
|------|------------|---------------------|----------------------|
| **None** | (no auth key) | Nothing | No auth header added |
| **Bearer** | `"bearer"` | Token or `env:VAR_NAME` | `Authorization: Bearer {token}` |
| **API Key** | `"api_key"` | Key + optional header name | `{api_key_header}: {value}` |
| **Custom Headers** | (use `headers` key) | Dict of header: value pairs | Headers added directly |
| **Browser Token** | `"browser_token"` | Login URL, storage state, intercept/script config | Playwright restores session, extracts token, adds to headers |
| **Dynamic REST** | `"dynamic_rest"` | Multi-step auth API config (steps, extract paths) | Calls auth API chain, extracts and applies token |

### Bearer Example

```json
"auth": { "type": "bearer", "value": "env:MY_CHATBOT_TOKEN" }
```
-> At runtime: `Authorization: Bearer <value_of_MY_CHATBOT_TOKEN>`

### API Key Example

```json
"auth": { "type": "api_key", "value": "my-key" },
"api_key_header": "X-API-Key"
```
-> Header: `X-API-Key: my-key`

---

## PART 13: BROWSER TOKEN AUTH DEEP DIVE

**File:** `app/connections/browser_auth.py`

### Architecture Problem Solved

Playwright on Windows requires `asyncio.ProactorEventLoop`. FastAPI/Uvicorn runs on `asyncio.SelectorEventLoop`. They cannot share the same loop. Solution: spawn a dedicated daemon thread (`_PlaywrightThread`) with its own ProactorEventLoop. All Playwright objects live exclusively in this thread. The `BrowserAuthManager` bridges between them using `asyncio.run_coroutine_threadsafe`.

### Complete Browser Token Flow

**Phase 1 -- Login (interactive)**

```
POST /connections/browser-auth/start  { "url": "https://client.com/login" }
        |
        v  browser_auth_manager.start_session(url)
           -> _PlaywrightThread._async_start(url)
           -> _BrowserAuthSession.start()
           -> playwright.chromium.launch(headless=False)  <- VISIBLE BROWSER
           -> page.goto(url)
        |
        v  Returns session_id to frontend
        |
[HUMAN LOGS IN MANUALLY IN THE BROWSER WINDOW]
        |
        v
POST /connections/browser-auth/save  { session_id, connection_name, expected_url, ... }
        |
        v  browser_auth_manager.save_verified_session(session_id, path, BrowserAuthCheck)
        |
        v  BrowserAuthSession.wait_for_auth(check)    <- Polls until login detected
           Checks: expected_url in page.url
                   required_cookie present in context.cookies()
                   authenticated_selector visible on page
        |
        v  BrowserAuthSession.save(path)              <- Saves Playwright storage_state
           context.storage_state(path="auth-state-ClientName.json")
           _append_session_storage(path)              <- Augments with sessionStorage data
        |
        v  verify_saved_state()                       <- Opens HEADLESS browser with saved state
           Checks login still valid in restored context
        |
        v  Returns BrowserAuthSaveResult
```

**Phase 2 -- Token Extraction (during evaluation)**

```
RestChatAdapter.__init__() detects auth.type == "browser_token"
        |
        v  _resolve_browser_token(auth)
        |
        v  browser_auth_manager.extract_browser_token_sync(
               url=auth.url,
               storage_state="auth-state-ClientName.json",
               intercept_pattern="https://api.client.com/*/auth",
               token_path="token",
               trigger_script="doSomething()",
               delete_cookies=["old_session"]
            )
        |
        v  _async_extract_browser_token():
           1. Launch headless Chromium
           2. Restore storage_state (cookies + localStorage + sessionStorage)
           3. Optionally delete specified cookies
           4. Set up response interceptor matching intercept_pattern
              OR request interceptor for header:Authorization token_path
           5. Navigate to url
           6. Optionally run trigger_script
           7. Wait for matching network response, extract token via token_path
        |
        v  token returned
           self.headers["Authorization"] = "Bearer {token}"
```

### Key Configuration Fields

| Field | Purpose |
|-------|---------|
| `url` | Page to navigate to for token extraction |
| `storage_state` | Path to saved auth state JSON |
| `intercept_pattern` | fnmatch pattern to match network response URLs |
| `token_path` | Dot-path in JSON response body (or `"header:Authorization"` for request headers) |
| `trigger_script` | JavaScript to evaluate after page load to trigger the auth network call |
| `delete_cookies` | Cookies to delete before navigation (to force token refresh) |
| `header_name` | Which HTTP header to set (default: `Authorization`) |
| `header_format` | Format string for header value (default: `"Bearer {token}"`) |

---

## PART 14: INTERACTIVE CHATBOT / USER ACTION ENGINE

**Directory:** `app/interactive/`

The User Action Engine is an optional feature (`settings.enable_user_action_engine = False` by default in `config.py`). When enabled, instead of the simple simulator loop, `ConversationOrchestrator` handles turns.

### What It Does

When a chatbot returns UI components (buttons, dropdowns, forms), the engine:
1. **Detects components** -- `response_understanding.py:ResponseUnderstanding` parses the chatbot's response metadata for interactive elements
2. **Plans interactions** -- `decision_planner.py:DefaultDecisionPlanner.plan()` maps components to an `InteractionPlan`
3. **Validates** -- `action_validator.py` checks the plan is coherent
4. **Executes** -- `action_executor.py:ActionExecutor` calls adapter methods to perform the actual action

### Supported Component -> Interaction Mapping

| Component | InteractionType | Adapter Method |
|-----------|----------------|---------------|
| `button`, `quick_reply` | `button`, `quick_reply` | `adapter.click_button()` |
| `dropdown` | `dropdown` | `adapter.select_dropdown()` |
| `checkbox` | `checkbox` | `adapter.select_checkbox()` |
| `radio_button` | `radio_button` | `adapter.select_radio()` |
| `date_picker` | `date_picker` | `adapter.pick_date()` |
| `time_picker` | `time_picker` | `adapter.pick_time()` |
| `file_upload` | `file_upload` | `adapter.upload_file()` |
| `text` / `markdown` / `image` / etc. | None -- informational only | -- |

### Scenario Step Mode (Always Available)

Even without the action engine enabled, the `TestScenario.steps` field allows explicit scripted steps:
- `send:` -- send a text message
- `click_button:` -- click a button (browser adapter)
- `select:` -- select dropdown
- `radio:` -- select radio
- `checkbox:` -- check/uncheck
- `upload:` -- upload a file
- `otp:` -- enter OTP code
- `date:` / `time:` -- pick date/time
- `form:` -- fill multiple fields
- `search:` -- search field

This is implemented in `executor.py:_execute_chatbot_steps()` (line 267-533).

---

## PART 15: RAG -- CONCEPT EXPLAINED

**Retrieval-Augmented Generation (RAG)** is a technique where an AI agent, before answering, searches a knowledge base for relevant documents and uses those documents to ground its answer.

```
User question: "What is your return policy?"
        |
        v  Client's RAG pipeline (NOT built by EvalForge)
        |
        v  Vector search -> retrieved chunks:
             ["Returns accepted within 30 days...", "No receipt required..."]
        |
        v  LLM generates answer using retrieved chunks:
             "You can return items within 30 days without a receipt."
        |
        v  Agent response sent to user
```

**EvalForge does NOT build the client's RAG.** The client already has their RAG system deployed. EvalForge evaluates the **quality** of the agent's answer by comparing it to what the RAG system actually retrieved.

### Critical Distinction

| Term | What It Is |
|------|-----------|
| **Agent Answer** | The text the chatbot sends to the user |
| **Retrieved RAG Context / Evidence** | The document chunks the RAG system fetched before generating the answer |

**The retrieved context is NOT the answer.** The answer is what the LLM generated after reading the retrieved context. EvalForge needs BOTH to evaluate faithfulness.

---

## PART 16: RAG IMPLEMENTATION

**Files:**
- `app/rag.py` -- evidence extraction utility
- `app/models/conversation.py` -- `RAGEvidence` model
- `app/evaluation_service.py` -- `_rag_evidence_by_turn()`
- `app/evaluator.py` -- RAG metrics

### RAGEvidence Model

```python
# app/models/conversation.py line 6-11
class RAGEvidence(BaseModel):
    available: bool = False        # Was retrieval evidence captured?
    source: str = "unknown"        # "agent_retrieval" | "reference_context"
    contexts: list[str]            # Retrieved document chunks (text strings)
    citations: Optional[list]      # Optional citation references
    metadata: Optional[dict]       # Extra metadata from config
```

Every `ConversationMessage` from the agent can carry an optional `rag_evidence` field.

### Extract RAG Evidence Function

**File:** `app/rag.py:extract_rag_evidence()` line 24-69

```python
def extract_rag_evidence(data: dict, config: dict) -> RAGEvidence | None:
    # 1. Find rag_config or rag in config
    # 2. Get context_path (dot-path to retrieved chunks)
    # 3. Walk data using get_values_by_path()
    # 4. Normalize each value (str, dict with "content"/"text"/"chunk"/"snippet"/"page_content")
    # 5. Deduplicate
    # 6. Return RAGEvidence(available=True, contexts=[...])
```

The dot-path syntax supports arrays: `retrieved_chunks[].content` -> iterates the array, extracts `.content` from each item.

### Complete RAG Trace

```
User question (turn N)
        |
Client RAG agent
        |
Agent answer + evidence in HTTP response:
  {
    "answer": "You can return within 30 days.",
    "retrieved_chunks": [{"content": "Returns accepted within 30 days..."}]
  }
        |
RestChatAdapter._extract_rag_evidence_for_response(response_data)
-> extract_rag_evidence(data, config)
-> RAGEvidence(available=True, contexts=["Returns accepted within 30 days..."])
        |
ConversationMessage(role="agent", content="...", rag_evidence=RAGEvidence(...))
        |
EvaluationService._rag_evidence_by_turn(transcript)
-> Collects: [{input: question, actual_output: answer, contexts: [...]}]
        |
evaluator.py:evaluate_transcript(rag_evidence_by_turn=[...])
-> For each turn:
    LLMTestCase(input=question, actual_output=answer, retrieval_context=chunks)
    HallucinationMetric.measure(test_case)
    FaithfulnessMetric.measure(test_case)
    AnswerRelevancyMetric.measure(test_case)
        |
MetricResult(name="Faithfulness (Turn 1)", score=0.92, category="rag")
```

---

## PART 17: HOW CLIENT CONNECTS RAG

### Mode 1 -- Evidence in Same Response

The chatbot API returns the retrieved chunks alongside the answer in a single response.

**EvalForge connection config:**
```json
"rag_config": {
  "enabled": true,
  "context_path": "retrieved_chunks[].content",
  "citation_path": "retrieved_chunks[].source",
  "source_type": "agent_retrieval"
}
```

**Code path:**
```
RestChatAdapter._extract_rag_evidence_for_response(response_data)
  -> mode != "separate_api"
  -> extract_rag_evidence(response_data, config)  (app/rag.py)
  -> get_values_by_path(data, "retrieved_chunks[].content")
  -> RAGEvidence(available=True, contexts=[...])
```

### Mode 2 -- Separate Evidence / Trace API

The chatbot returns an answer + a correlation ID. A second API exposes the retrieved evidence for that request.

**EvalForge connection config:**
```json
"rag_config": {
  "enabled": true,
  "mode": "separate_api",
  "correlation_path": "request_id",
  "evidence_request": {
    "url": "https://api.client.com/trace/{correlation_id}",
    "method": "GET",
    "use_same_auth": true
  },
  "context_path": "retrieved_chunks[].content"
}
```

**Code path:**
```
RestChatAdapter._extract_rag_evidence_for_response()
  -> mode == "separate_api"
  -> _fetch_rag_evidence_from_api(response_data, rag_config)  (rest.py line 448-506)
  -> get_values_by_path(response_data, "request_id") -> ["abc-123"]
  -> url = "https://api.client.com/trace/abc-123"  (substitution)
  -> requests.get(url, headers=self.headers)
  -> extract_rag_evidence(evidence_data, {rag_config: rag_config})
  -> RAGEvidence(available=True, contexts=[...])
```

**Same-turn correlation guarantee:** Evidence is fetched immediately after the send call, before the next user turn. Evidence from turn N is stored on turn N's `ConversationMessage`. It never leaks to turn N+1.

---

## PART 18: CLIENT ONBOARDING CHECKLIST FOR RAG

### For Normal Chatbot Evaluation (No RAG)

**Required:**
- Chatbot endpoint URL
- HTTP method (POST usually)
- Request format (which field to put the message in)
- Response format (which field contains the reply)
- Authentication (none / bearer token / API key / browser login)

### For RAG Evaluation (Same-Response Mode)

**Additional Required:**
- Which field in the response contains the retrieved chunks (`context_path`)
- Format of retrieved chunks (plain string? dict with "content" key?)

### For RAG Evaluation (Separate Evidence API Mode)

**Additional Required:**
- Which field in the chat response is the correlation ID (`correlation_path`)
- Evidence API URL with `{correlation_id}` placeholder
- HTTP method for evidence API (GET or POST)
- Which field in evidence response contains the chunks (`context_path`)

---

## PART 19: WHAT IF CLIENT HAS NO RAG?

If no `rag_config` is configured in the connection, `extract_rag_evidence()` returns `None`. Every `ConversationMessage.rag_evidence` is `None`.

In `evaluation_service.py`:
- `rag_evidence_by_turn` -> returns `[]` (empty list)
- If `scenario.rag_context` is present -> `status="evaluated"`, `evidence_source="reference_context"` (static reference mode)
- If no `rag_context` either -> `status="not_evaluated"`

**Result:** Normal chatbot metrics (Goal Completion, Tone Adherence, Conversational Quality) still run. RAG-specific metrics do not run. The evaluation still completes normally.

Code: `evaluation_service.py:_resolve_rag_status()` line 286-309.

---

## PART 20: WHAT IF CLIENT CANNOT EXPOSE RAG EVIDENCE?

If the client's chatbot uses RAG internally but cannot expose what was retrieved:

- `rag_evidence_by_turn = []` -- no runtime evidence
- If `scenario.rag_context` is provided: evaluation uses that as static ground-truth for faithfulness checking. `rag_evaluation.evidence_source = "reference_context"`.
- If no reference context either: `rag_evaluation.status = "not_evaluated"`.

**Important distinction:**
Reference context (`scenario.rag_context`) is static, curated ground truth. It is NOT the runtime retrieved context. Do not present reference context evaluation as equivalent to live retrieval evidence evaluation.

---

## PART 21: RAG METRICS

**File:** `app/evaluator.py`

### All Current Metrics

| Metric | DeepEval Class | Category | What It Checks |
|--------|---------------|----------|---------------|
| **Goal Completion** | `GEval` | base | Did the agent successfully accomplish the user's goal? |
| **Persona and Tone Adherence** | `GEval` | base | Was the agent's tone professional and consistent? |
| **Conversational Quality** | `ConversationalGEval` | base | Context tracking, intent understanding, consistency across turns |
| **Hallucination** | `HallucinationMetric` | rag | Does the answer contain statements not supported by retrieved context? |
| **Answer Relevancy** | `AnswerRelevancyMetric` | rag | Is the answer relevant to the question asked? |
| **Faithfulness** | `FaithfulnessMetric` | rag | Are all claims in the answer supported by the retrieval context? |

**Note:** `HallucinationMetric` returns high score = more hallucination. EvalForge inverts it: `normalized_score = 1.0 - raw_score` (line 301).

### When RAG Metrics Run

- `rag_context` provided in scenario: `HallucinationMetric`, `AnswerRelevancyMetric`, `FaithfulnessMetric` added to the single test case
- `rag_evidence_by_turn` populated (runtime mode): a separate `LLMTestCase` is created for **each agent turn** with evidence. Three metrics run per turn. Result names include `(Turn N)` suffix.

### Overall Score Aggregation

```python
# evaluation_service.py line 330-340
def _balanced_overall_score(metrics):
    base_avg = average([m.score for m in base_metrics])
    rag_avg  = average([m.score for m in rag_metrics])
    return average([base_avg, rag_avg])  # equal weight regardless of metric count
```

This prevents many RAG turns from dominating the score over conversation quality.

### Judge Models

- **Primary:** `GroqJudge` -> Groq API, model `llama-3.1-8b-instant` (configurable via `groq_model`)
- **Fallback:** `GeminiJudge` -> Google `gemini-2.0-flash` (activates if Groq fails)

---

## PART 22: VOICE AGENT

**Directory:** `app/voice/`, `app/adapters/voice/`

### Architecture

```
ScenarioExecutor._execute_voice()
        |
        v  VoicePersonaEngine(persona, adapter, tts_provider, max_turns)
           app/voice/persona.py
        |
        v  engine.run_automated_session()
           Drives conversation loop via voice adapter
        |
        v  VoiceConversation  (app/models/voice.py)
           [VoiceTurn(speaker, text, timestamp, audio_path, latency_ms, confidence)]
        |
        v  voice_to_normalized_conversation(vc)
           app/voice/converter.py
           Maps Speaker.user -> "simulated_user"
                Speaker.agent -> "agent"
           Extracts rag_evidence per turn from turn.metadata if rag_config set
        |
        v  NormalizedConversation  (shared model)
        |
        v  EvaluationService.evaluate(exec_result, scenario)
           Same evaluation as chatbot
        |
        v  + run_voice_metrics(voice_conversation, voice_config)
             app/voice/metrics.py
             Voice-specific metrics: latency, interruption rate, etc.
```

### Registered Voice Adapters

| Adapter | File | What It Does |
|---------|------|-------------|
| `livekit` | `adapters/voice/livekit.py` | LiveKit WebRTC-based real-time voice session |
| `local` | `adapters/voice/local.py` | Local microphone + speakers (sounddevice + piper-tts + faster-whisper) |
| `fake` | `adapters/voice/fake.py` | In-memory scripted responses for testing |

### RAG in Voice

Each `VoiceTurn` has a `rag_evidence` field and a `metadata` dict. If the voice adapter populates `turn.rag_evidence` or `turn.metadata` with retrieval data, and `rag_config` is configured in the connection, `voice/converter.py:_turn_rag_evidence()` extracts `RAGEvidence` and attaches it to the `ConversationMessage`. The same evaluation path applies.

---

## PART 23: AI CALLING AGENT

**Directory:** `app/calling/`

This subsystem handles evaluation of AI agents accessed via telephone infrastructure (PSTN, SIP, VoIP APIs like Twilio, Vapi, Retell, Bland).

### Key Models

```python
class CallDirection(str, Enum):   # inbound | outbound
class CallStatus(str, Enum):      # created -> dialing -> ringing -> connected -> in_progress -> completed | failed
class CallProvider(str, Enum):    # custom | twilio | livekit_sip | vapi | retell | bland | custom_sip
class CallSession(BaseModel):     # session_id, run_id, direction, provider, status, from/to numbers
class CallTranscriptTurn(BaseModel):  # speaker, text, turn_index, timestamp, confidence
class NormalizedCallTranscript(BaseModel):  # session_id, run_id, turns[], language, source
class CallingExecutionResult(BaseModel):    # success, session, transcript, artifacts, events
```

### Provider Status

| Provider | Runtime Status |
|----------|---------------|
| `mock` | Fully available -- in-memory, no credentials needed |
| `twilio` | `TwilioProvider` implemented -- real API calls with credentials |
| `vapi`, `retell`, `bland` | Config accepted, UI shows requirements, runtime uses mock |
| `sip`, `custom` | Config accepted, runtime uses mock |

---

## PART 24: WHY VOICE AND AI CALLING ARE DIFFERENT

### Voice Agent Evaluation (`app/voice/`)

- **Use case:** Agent with real-time audio/voice capabilities (WebRTC, LiveKit, local microphone)
- **Transport:** WebSocket/WebRTC audio streams
- **EvalForge role:** Plays a simulated user's audio (TTS), receives agent audio (STT), drives a real-time conversation session
- **Transcript source:** STT of the actual audio exchange

### AI Calling Agent Evaluation (`app/calling/`)

- **Use case:** Agent accessible via telephone (PSTN/SIP) -- e.g., customer calls a phone number and talks to an AI
- **Transport:** Telephone network (PSTN), SIP trunk, or calling API (Twilio, Vapi, Retell, Bland)
- **EvalForge role:** Initiates or prepares a phone call, manages the call lifecycle, retrieves recordings, sends audio for STT transcription
- **Transcript source:** Call recording (audio file) -> STT provider (Whisper), or provider-supplied transcript

**Practical difference:** Voice uses real-time audio streaming. Calling uses telephone infrastructure with recordings and webhooks. A calling evaluation may involve waiting for a call to complete before transcription becomes available.

---

## PART 25: OUTBOUND CALLING FLOW

**File:** `app/calling/ui_api.py:run_calling_evaluation()` (line 377-444)

```
POST /calling/connections/{id}/run
{ scenario_path, direction: "outbound", to_number: "+1-555-..." }
        |
        v  _load_scenario(scenario_path) -> TestScenario
        |
        v  _provider_config(raw)  -> CallingProviderConfig
        |
        v  CallingEvaluationRuntimeRunner().run(scenario, provider_config, direction, to, from_)
           calling/evaluation_runner.py
        |
        v  CallingEvaluationRunner.run_mock_call(to, from_, scenario_id, direction)
           calling/runner.py
        |
        v  provider_adapter.start_outbound_call(to, from_, metadata)
           MockCallProvider: creates -> dialing -> ringing -> connected
           TwilioProvider: client.calls.create(to, from_, url, ...)
        |
        v  simulate_conversation_started(session) -> in_progress
        |
        v  provider_adapter.end_call(session) -> completed
        |
        v  build_mock_transcript(session) -> NormalizedCallTranscript
        |
        v  EvidenceBuilder.build(session, events, recordings, transcript)
           -> ConversationEvidence
        |
        v  ConversationNormalizer.normalize(evidence)
           -> call_transcript_to_normalized_conversation()
           -> NormalizedConversation (same shared model as chatbot)
        |
        v  CallingExecutionResult
        |
        v  CallingEvaluationBridge.evaluate(execution, scenario)
           -> CallingResultConverter.to_execution_result()
           -> EvaluationService.evaluate(exec_result, scenario)
        |
        v  EvaluationResult (same evaluation path as chatbot)
        |
        v  CallingRunResponse returned to frontend
```

### State Transitions (Mock Provider)

```
created -> dialing -> ringing -> connected -> in_progress -> completed
```

Managed by `CallLifecycleManager.transition()` in `calling/lifecycle.py`, validated by `CallStateMachine`.

---

## PART 26: INBOUND CALLING

**Current Status:** PARTIAL -- infrastructure exists, not end-to-end

**What is implemented:**
- `CallDirection.inbound` enum value and model support
- `MockCallProvider.prepare_inbound_call()` creates an inbound session in `prepared` state
- `MockCallProvider.simulate_inbound_connected()` transitions through `ringing -> connected`
- `TwilioProvider.prepare_inbound_call()` creates a placeholder session
- `CallingEvaluationRunner.run_mock_call()` handles `direction=inbound`
- Webhook handler (`calling/twilio_webhook.py`, `calling/webhook_handler.py`) can process Twilio status callbacks

**What is NOT fully implemented:**
- Real inbound webhook flow -- no live HTTP endpoint that Twilio calls when an actual inbound call arrives
- Inbound call waiting -- no mechanism to hold EvalForge until a real phone call arrives
- Real PSTN inbound end-to-end triggering

---

## PART 27: WHAT WE NEED FROM CLIENT FOR AI CALLING

### A. Client Has a Telephone AI Agent (PSTN/SIP)

**For outbound evaluation:**

| Field | Notes |
|-------|-------|
| Provider name (twilio/vapi/retell/bland/sip/custom) | Required |
| Phone number to call (to_number) | Required |
| Provider credentials | Required (account_sid+auth_token for Twilio, api_key for others) |
| From number (EvalForge's outbound number) | Required for Twilio/Retell/Bland |
| Voice URL (TwiML webhook) | Required for Twilio |
| Agent ID / assistant ID | Required for Vapi/Retell |

### B. Client Has Voice/WebRTC

| Field | Notes |
|-------|-------|
| LiveKit server URL + API key + secret | Required for LiveKit voice adapter |
| Agent name in LiveKit room | Required |

### C. Mock Provider (Always Works)

The `mock` provider requires NO real credentials. It simulates the entire call lifecycle in memory. Useful for testing the evaluation pipeline.

---

## PART 28: WHAT IF CLIENT HAS NO CALLING CONNECTION INFO?

| Situation | What Works |
|-----------|-----------|
| Client has chatbot API | Full chatbot + RAG evaluation works |
| Client has voice/WebRTC (LiveKit) | Voice evaluation works |
| Client has telephone AI but no credentials | Calling evaluation blocked |
| Client has no API at all | Browser adapter can evaluate web-based chatbot UI |
| Client has no accessible interface | EvalForge cannot connect |

For the calling subsystem specifically, the `mock` provider always works for pipeline testing. For real telephone agents, EvalForge needs provider access.

---

## PART 29: CALLING RAG

**Files:** `app/calling/normalizer.py`, `app/models/conversation.py`

### How RAG Evidence Flows in Calling

```
CallTranscriptTurn.metadata  <- Set by calling adapter/webhook/provider
        |
        v  calling/normalizer.py:_turn_rag_evidence(turn, rag_config)
           Only runs for speaker=agent turns
           Calls extract_rag_evidence(metadata, {"rag_config": rag_config})
        |
        v  RAGEvidence(available=True, contexts=[...])
           Attached to ConversationMessage.rag_evidence
        |
        v  EvaluationService._rag_evidence_by_turn(transcript)
           Collects per-turn evidence: {input, actual_output, contexts}
        |
        v  evaluate_transcript(rag_evidence_by_turn=[...])
           Same DeepEval metrics as chatbot RAG
        v
MetricResult (RAG category)
```

### Why STT Text Is Not Automatically RAG Evidence

The transcribed text (what the agent said) is the **answer** -- it is `actual_output`. RAG evidence is the **retrieved context** used to generate that answer. The calling provider must explicitly include retrieved chunks in `CallTranscriptTurn.metadata` (configured via `rag_config.context_path` pointing into the metadata dict).

---

## PART 30: NORMALIZATION

### Why Normalization Exists

EvalForge supports three channels (chatbot, voice, calling), each with different data models. Normalization converts all of them to a unified format before evaluation.

### The Shared Model

```python
# app/models/conversation.py
class NormalizedConversation(BaseModel):
    run_id: str
    session_id: str
    channel: str         # "chatbot" | "voice" | "calling"
    messages: list[ConversationMessage]
    retrieval_context: Optional[list[str]]
    start_time: Optional[str]
    end_time: Optional[str]
    status: str
    metadata: Optional[dict]

class ConversationMessage(BaseModel):
    role: str            # "simulated_user" | "agent" | "system"
    content: str         # The actual text
    turn_index: int
    timestamp: Optional[str]
    attachments: Optional[list[str]]
    metadata: Optional[dict]
    rag_evidence: Optional[RAGEvidence]  # Per-turn retrieval evidence
```

### Normalizer Files

| Channel | Input | Normalizer | Output |
|---------|-------|-----------|--------|
| **Chatbot** | `adapter.get_conversation()` | Built into adapter | `NormalizedConversation` |
| **Voice** | `VoiceConversation` | `app/voice/converter.py:voice_to_normalized_conversation()` | `NormalizedConversation` |
| **Calling** | `NormalizedCallTranscript` | `app/calling/normalizer.py:call_transcript_to_normalized_conversation()` | `NormalizedConversation` |

After normalization, `EvaluationService.evaluate()` and `evaluate_transcript()` receive identical input regardless of channel.

---

## PART 31: EVALUATION ENGINE

**Files:** `app/evaluation_service.py`, `app/evaluator.py`

### EvaluationService.evaluate()

```python
# evaluation_service.py line 82-208
def evaluate(self, execution_result: ExecutionResult, scenario: TestScenario) -> EvaluationResult:
    # 1. Guard: if execution failed, return failure result immediately
    # 2. Build per-turn RAG evidence list
    # 3. Determine RAG evaluation status (agent_retrieval / reference_context / not_evaluated)
    # 4. Call evaluate_transcript() -> list[MetricResult]
    # 5. Optional: run voice metrics (if voice channel)
    # 6. Optional: BackendValidator.validate() (currently no-op placeholder)
    # 7. _balanced_overall_score(metrics)
    # 8. passed = overall_score >= scenario.pass_threshold
    # 9. Return EvaluationResult
```

### Input/Output Summary

| Input | Source |
|-------|--------|
| `persona` | `TestScenario.persona` (goal, name, tone) |
| `transcript` | `NormalizedConversation.messages` |
| `rag_context` | `TestScenario.rag_context` or `None` |
| `rag_evidence_by_turn` | From `_rag_evidence_by_turn(transcript)` |

| Output | Type |
|--------|------|
| `list[MetricResult]` | name, score (0.0-1.0), reason, passed, category, evidence_source, turn_index |

---

## PART 32: STORAGE / PERSISTENCE

### Evaluation Results

**File:** `app/storage.py`
**Database:** `eval_results.db` (SQLite)

```sql
CREATE TABLE IF NOT EXISTS test_runs (
    run_id      TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    channel     TEXT NOT NULL,
    overall_score REAL NOT NULL,
    passed      INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    payload     TEXT NOT NULL   -- Full JSON of TestRunResult
);
```

Functions: `save_run()`, `get_run()`, `list_runs()`
Used by: legacy `/test-runs` endpoint path via `orchestrator.py`

### Agent Connections

**File:** `app/connections/storage.py`
**Database:** `connections.db` (SQLite)

```sql
CREATE TABLE IF NOT EXISTS agent_connections (
    id      TEXT PRIMARY KEY,
    payload TEXT NOT NULL   -- Full JSON of AgentConnection
);
```

### Calling Connections

**Storage:** `calling_connections.json` (flat JSON file)

### Browser Auth States

**Files:** `auth-state-{ConnectionName}.json`
Playwright `storage_state` format (cookies + localStorage + sessionStorage).

### What Is NOT Persisted

- Results from the new `/connections/{id}/evaluate` path -- **NOT saved to SQLite** (returned to frontend only). Only the legacy `/test-runs` path saves to SQLite.

---

## PART 33: FRONTEND

**Files:** `frontend/index.html`, `frontend/static/app.js`, `frontend/static/styles.css`

Vanilla JS single-page application. No React, Vue, or Angular.

### Main Sections

| Section | What It Does | Key API Calls |
|---------|-------------|---------------|
| **Dashboard** | Overview, recent evaluations | `GET /test-runs`, `GET /connections` |
| **Connections** | List all saved chatbot connections | `GET /connections` |
| **Add/Edit Connection** | Form: name, type, adapter, config (URL, auth, RAG config, mappings) | `POST /connections`, `PATCH /connections/{id}` |
| **Test Connection** | Verify connectivity | `POST /connections/{id}/test` |
| **Browser Auth** | Open browser for login, save state | `POST /connections/browser-auth/start`, `POST /connections/browser-auth/save` |
| **Scenarios** | List available YAML files | `GET /scenarios` |
| **Evaluations** | Select connection + scenario, run, view results | `POST /connections/{id}/evaluate` |
| **AI Calling** | Calling connections, run calling evaluation | `POST /calling/connections/{id}/run` |
| **Reports/Results** | Transcript display, metric scores, RAG summary | Result JSON rendered inline |

---

## PART 34: SECURITY

### What Is Currently Implemented

| Concern | What Is Done |
|---------|-------------|
| **Credential redaction in API responses** | `_safe_connection_config()` blanks `auth.value` before returning connection JSON |
| **Credential redaction in logs** | `AgentConnection.__repr__` omits `config`; `_sanitise_error_message()` redacts key/token/secret patterns |
| **Env var resolution** | `"value": "env:MY_KEY"` resolved at runtime; never stored as raw credential |
| **Path traversal prevention** | `scenarios/save` sanitizes filename (alphanumeric only, no `..` or `/`) |
| **Browser auth isolation** | Login sessions run in dedicated Playwright thread |
| **Calling credentials** | `SecretStr` for credential values; response model shows `"configured"` not actual values |

### Real Limitations

- **No user authentication** -- anyone who reaches the server can access all connections
- **CORS open** -- `allow_origins=["*"]` -- development setup only
- **SQLite on local filesystem** -- not suitable for production multi-user deployment
- **Auth state files on disk** -- unencrypted JSON files containing full browser session state
- **Calling credentials in JSON** -- `calling_connections.json` stores credentials as plain text after `SecretStr` unwrapping
- **Debug print statements** -- `rest.py` line 286-313 contains `print()` statements logging auth config to stdout

---

## PART 35: ERROR HANDLING

### What Happens on Failure

| Failure | Behavior |
|---------|---------|
| Chatbot API fails (HTTP error) | `ExecutionResult(success=False, error=...)` returned |
| Authentication fails | Adapter instantiation raises `ValueError` -> evaluation blocked |
| Response timeout (REST) | `requests.Timeout` -> `ExecutionResult(success=False)` |
| Polling timeout (multi-step) | `RestAdapterTimeoutError` -> `ExecutionResult(success=False)` |
| RAG evidence API fails | Logged as warning, returns `None` -> evaluation continues without RAG metrics |
| RAG evidence missing | `rag_evaluation.status = "not_evaluated"` -> base metrics still run |
| Voice call fails | `ExecutionResult(success=False)` |
| Calling provider fails | `CallingRunResponse(success=False, error=...)` |
| Evaluator metric fails | Caught per-metric -> `MetricResult(score=0.0, passed=False, reason="Metric failed: ...")` -- **evaluation continues with other metrics** |
| Groq judge unavailable | Falls back to Gemini judge |

### Graceful vs. Blocking Failures

| Category | Blocking? |
|----------|----------|
| Adapter instantiation failure | Yes -- blocks evaluation |
| Connection disabled | Yes -- blocks evaluation |
| Scenario file not found | Yes -- returns 404 |
| RAG evidence API failure | No -- degrades gracefully (RAG metrics skipped) |
| Single DeepEval metric failure | No -- score 0.0, others continue |
| Groq judge unavailable | No -- falls back to Gemini |

---

## PART 36: IMPLEMENTED VS. PARTIAL VS. NOT IMPLEMENTED

### FULLY IMPLEMENTED

- FastAPI backend with connection CRUD, test, evaluate endpoints
- AgentConnection model + SQLite persistence
- AdapterRegistry + ConnectionManager (pluggable adapter pattern)
- RestChatAdapter -- legacy mode, multi-step polling mode, RAG (same-response + separate API), browser token auth, dynamic REST auth, attachment upload, interactive component metadata
- BrowserChatAdapter -- full Playwright-driven UI interaction
- FakeChatAdapter -- in-memory mock for testing
- ScenarioExecutor -- chatbot and voice dispatch, scenario steps engine
- User Simulator (Groq-powered, full conversation history, persona adherence, attachment support)
- DeepEval integration (GEval, ConversationalGEval, HallucinationMetric, FaithfulnessMetric, AnswerRelevancyMetric)
- GroqJudge (primary) + GeminiJudge (fallback)
- RAG evidence extraction (dot-path traversal, array support, multi-format normalization)
- Per-turn RAG evaluation (separate test case per turn)
- Balanced score aggregation (base/RAG category separation)
- Browser auth capture (interactive login -> storage_state -> verify in headless browser)
- Browser token extraction (intercept network response / request header)
- NormalizedConversation model (shared across all channels)
- Voice evaluation pipeline (LiveKit, local, fake adapters)
- Voice -> NormalizedConversation converter
- AI Calling models (session, transcript, events, artifacts)
- MockCallProvider (full lifecycle simulation in memory)
- TwilioProvider (outbound call creation -- real API calls)
- Calling lifecycle state machine
- Calling evaluation bridge (calling result -> EvaluationService)
- Calling normalizer (CallTranscriptTurn -> NormalizedConversation)
- Calling RAG support (via turn.metadata + rag_config)
- Calling connections storage (JSON file)
- Calling API (CRUD + run endpoint)
- Frontend SPA
- Interactive/User Action Engine models and planner
- Scenario YAML library
- SQLite for evaluation results and connections

### PARTIAL / SCAFFOLDED

- **WebSocketChatAdapter:** `connect()` is a stub. Only works with pre-scripted `responses` list in config. No real WebSocket connection.
- **Interactive/User Action Engine:** Fully modeled, but `settings.enable_user_action_engine = False` by default.
- **Inbound Calling:** Models exist, mock works. Real inbound webhook -> wait -> evaluate flow NOT wired end-to-end.
- **Non-mock calling providers (Vapi, Retell, Bland, SIP):** Config accepted, runtime execution uses mock pipeline.
- **Twilio real calling:** `TwilioProvider.start_outbound_call()` implemented. End-to-end recording -> Whisper STT requires recording URL availability after call.

### NOT IMPLEMENTED

- User authentication / multi-tenancy
- Production database (Postgres/SQLAlchemy)
- Evaluation result persistence for new `/connections/{id}/evaluate` path
- SSE (Server-Sent Events) adapter
- SIP adapter (referenced in comments, not registered)
- Real-time streaming responses

---

## PART 37: TEST ARCHITECTURE

**Directory:** `tests/` -- 50+ test files, pytest-based

### Test Group -> Feature Map

| Test File | Feature |
|-----------|---------|
| `test_rest_adapter_generic.py` | REST adapter basic send/receive |
| `test_rest_browser_token.py` | Browser token auth extraction |
| `test_rest_rag_evidence_api.py` | Separate evidence API mode |
| `test_rest_multi_step.py` | Multi-step polling mode |
| `test_evaluation_service.py` | EvaluationService logic |
| `test_evaluator.py` | DeepEval metric execution |
| `test_evaluation_bridge.py` | Calling -> EvaluationService bridge |
| `test_scenario_executor.py` | ScenarioExecutor chatbot + voice |
| `test_voice_adapter.py` | Voice adapter tests |
| `test_voice_rag.py` | Voice RAG evidence extraction |
| `test_twilio_provider.py` | Twilio provider lifecycle |
| `test_webhook_handler.py` | Calling webhook processing |
| `test_decision_planner.py` | Interactive decision planner |
| `test_evidence_builder.py` | Calling evidence assembly |
| `test_conversation_normalizer.py` | Calling conversation normalizer |
| `test_rag_frontend_integration.py` | RAG config parsing from frontend |
| `test_evaluation_api.py` | REST API evaluation endpoints |

---

## PART 38: LIVE WALKTHROUGH FILE ORDER

| Order | File | Important Class/Function | Key Thing to Say |
|-------|------|--------------------------|-----------------|
| 1 | `requirements.txt` | -- | "14 dependencies. FastAPI, Pydantic, DeepEval, Groq, Gemini, Playwright, SQLite." |
| 2 | `app/main.py` | `FastAPI`, `include_router`, `create_test_run` | "Entry point. Two routers. Lifespan closes browser sessions on shutdown." |
| 3 | `app/schemas.py` | `Persona`, `TestScenario`, `MetricResult` | "Pydantic validates everything before any LLM call. Persona goal must be real, not blank." |
| 4 | `app/models/connection.py` | `AgentConnection`, `AgentType` | "Universal connection descriptor. adapter is a free-form string. Model never changes for new adapters." |
| 5 | `app/connections/storage.py` | `ConnectionRepository`, `save`, `get` | "Connections survive server restarts. Full JSON in payload column." |
| 6 | `app/connections/registry.py` | `AdapterRegistry.default()`, `_register_defaults()` | "Open/closed principle. New adapter = register one line here. Imports are lazy." |
| 7 | `app/connections/api.py` | `create_connection`, `evaluate_connection`, `_safe_connection_config` | "Credentials always blanked before returning to API consumer." |
| 8 | `app/connections/manager.py` | `ConnectionManager.test_connection`, `_sanitise_error_message` | "Manager is ignorant of vendors. Sanitizes error messages to prevent credential leakage." |
| 9 | `app/executor.py` | `ScenarioExecutor.execute`, `_execute_chatbot` | "Deep-merges scenario config into connection config. Conversation loop here." |
| 10 | `app/simulator.py` | `generate_next_user_turn`, `SYSTEM_TEMPLATE` | "Groq plays the user persona. Not scripted. [END_CONVERSATION] token stops the loop." |
| 11 | `app/adapters/chat/rest.py` | `RestChatAdapter.__init__`, `_resolve_browser_token`, `send_message` | "Two modes: legacy and multi-step. Auth resolved here. RAG extraction here." |
| 12 | `app/rag.py` | `extract_rag_evidence`, `get_values_by_path` | "Dot-path traversal. Array support with []. Multiple content field names handled." |
| 13 | `app/models/conversation.py` | `RAGEvidence`, `ConversationMessage`, `NormalizedConversation` | "Shared model for all channels. RAGEvidence is per-turn." |
| 14 | `app/evaluation_service.py` | `EvaluationService.evaluate`, `_rag_evidence_by_turn`, `_balanced_overall_score` | "Bridge between execution and scoring. Balanced score prevents RAG from dominating." |
| 15 | `app/evaluator.py` | `evaluate_transcript`, `GroqJudge`, `GeminiJudge` | "DeepEval framework. Three base metrics always. RAG metrics when evidence available. HallucinationMetric score is inverted." |
| 16 | `app/connections/browser_auth.py` | `BrowserAuthManager`, `_PlaywrightThread`, `_async_extract_browser_token` | "ProactorEventLoop vs SelectorEventLoop problem. Dedicated thread solution. Token extraction via network interception." |
| 17 | `app/calling/ui_api.py` | `run_calling_evaluation`, `_provider_config`, `_provider_requirements` | "Separate JSON storage. Provider requirements documented. Non-mock falls back to mock runtime currently." |
| 18 | `app/calling/runner.py` | `CallingEvaluationRunner.run_mock_call` | "Mock simulates full call lifecycle. No real calls. Transcript is placeholder." |
| 19 | `app/calling/normalizer.py` | `call_transcript_to_normalized_conversation` | "NormalizedCallTranscript -> NormalizedConversation. Same shared model as chatbot." |
| 20 | `app/voice/converter.py` | `voice_to_normalized_conversation` | "VoiceConversation -> NormalizedConversation. Same pattern as calling. Voice metadata preserved." |
| 21 | `scenarios/refund_request.yaml` | -- | "Complete scenario. Priya, damaged order, impatient tone, order number only if asked." |
| 22 | `app/storage.py` | `save_run`, `get_run`, `list_runs` | "Simple SQLite. Swap for Postgres without changing interface above." |

---

## PART 39: THREE DEMO SCRIPTS

### DEMO A -- Normal Chatbot Evaluation

**Goal:** Show the full chatbot evaluation pipeline end-to-end.

**Step 1 -- Add Connection**
- UI: Add Connection form -> Type=chatbot, Adapter=REST, endpoint=`http://localhost:8000/mock-chat`
- Open `app/connections/api.py:create_connection()` (line 149-160)
- Say: "Parse, validate with Pydantic, save to SQLite. Adapter name is just a string."

**Step 2 -- Test Connection**
- UI: Click "Test"
- Open `app/connections/manager.py:test_connection()` (line 86)
- Say: "Instantiates adapter, calls connect(), pass/fail. No AI involved. Credentials never in response."

**Step 3 -- Select Scenario**
- Open `scenarios/refund_request.yaml`
- Say: "Priya wants a refund. Impatient tone. Edge case: only gives order number if asked. Reference RAG context for faithfulness."

**Step 4 -- Run Evaluation**
- Open `app/simulator.py:generate_next_user_turn()` (line 65)
- Say: "Groq generates Priya's messages. Not a script. Full history every time."
- Open `app/evaluator.py:evaluate_transcript()` (line 250)
- Say: "Three metrics. Groq as judge. Reasons provided for each score."

**Step 5 -- View Results**
- Show: overall score, metric scores, transcript, pass/fail badge

---

### DEMO B -- RAG Chatbot Evaluation

**Goal:** Show how retrieval evidence flows through the evaluation.

**Step 1 -- Connection with RAG config**
- Open `app/rag.py:extract_rag_evidence()` (line 24)
- Say: "Dot-path traversal. retrieved_chunks[].content iterates the array and extracts content field."

**Step 2 -- Mock response with RAG**
```json
{
  "reply": "You can return within 30 days.",
  "retrieved_chunks": [{"content": "Return policy: 30 days, no receipt required"}]
}
```
- Open `app/models/conversation.py:ConversationMessage` + `RAGEvidence`
- Say: "Every agent turn now carries its retrieval evidence. This is what makes per-turn evaluation possible."

**Step 3 -- Per-turn RAG evaluation**
- Open `app/evaluation_service.py:_rag_evidence_by_turn()` (line 249)
- Say: "We collect question-answer-context triples for each agent turn with evidence."
- Open `app/evaluator.py` (line 329-384)
- Say: "Three metrics per turn: Hallucination, Faithfulness, AnswerRelevancy. Named 'Faithfulness (Turn 1)' etc."

---

### DEMO C -- AI Calling Evaluation

**Goal:** Show the calling pipeline, how it normalizes to the same evaluation engine.

**Step 1 -- Add Calling Connection**
- UI: Calling tab -> Add Connection -> Provider: Mock
- Open `app/calling/ui_api.py:create_calling_connection()` (line 307)
- Say: "Separate JSON storage. SecretStr wrapping. Response shows 'configured' not credentials."

**Step 2 -- Provider list**
- Open `app/calling/ui_api.py:_provider_requirements()` (line 146-155)
- Say: "Mock requires nothing. Twilio needs account_sid, auth_token, from_number, voice_url. Vapi needs api_key and assistant_id."

**Step 3 -- Run evaluation**
- Open `app/calling/runner.py:run_mock_call()` (line 43)
- Say: "Mock: create -> dial -> ring -> connect -> in_progress -> complete. No real calls."
- Open `app/calling/providers/mock.py:start_outbound_call()` (line 31)
- Say: "Each transition goes through the state machine. Invalid transitions rejected."

**Step 4 -- Normalization**
- Open `app/calling/normalizer.py:call_transcript_to_normalized_conversation()` (line 12)
- Say: "CallTranscriptTurn -> ConversationMessage. customer -> simulated_user. After this, evaluation is identical to chatbot."

**Step 5 -- Bridge**
- Open `app/calling/evaluation_bridge.py:evaluate()` (line 37)
- Say: "Same EvaluationService. Same DeepEval metrics. Different channel."

**Step 6 -- Show results**
- Say: "Same evaluation engine. Same metrics. Vendor-neutral design."

---

## PART 40: Q&A PREPARATION

**Q: Why do we need adapters?**
Different AI platforms expose their chatbots through completely different interfaces -- REST APIs, WebSocket, web UI only. Adapters translate between EvalForge's standard interface and each platform's actual transport. Adding a new adapter doesn't change any other code.

**Q: How do we support a new vendor?**
Create a class implementing `ChatAdapter` or `CallProviderAdapter`. Register it in `connections/registry.py:_register_defaults()` with one `registry.register()` call. No other files change.

**Q: How does authentication work?**
The adapter reads the `auth` section of the connection config. `bearer` and `api_key` set headers directly. `browser_token` runs a headless Playwright browser to extract a token from network responses. `dynamic_rest` calls an auth API chain. All credential values can reference environment variables with `env:VAR_NAME`.

**Q: Why Playwright?**
Some client chatbots only exist as web UIs -- they have no exposed API. Playwright lets EvalForge automate a real browser to type, click, and read responses just like a human would. It also handles complex browser-based authentication flows where the auth token only exists in memory.

**Q: What is RAG?**
RAG stands for Retrieval-Augmented Generation. Before answering, the AI searches a knowledge base for relevant documents and uses those documents to ground its answer. EvalForge evaluates whether the AI's answer is faithful to what it actually retrieved.

**Q: Are we building the client's RAG?**
No. The client already has their RAG system deployed. EvalForge evaluates the quality of the RAG system's outputs -- did the agent answer faithfully based on what it retrieved?

**Q: How do we know what RAG retrieved?**
Two ways: either the chatbot API returns the retrieved chunks in the same response, or there's a separate evidence/trace API we call with a correlation ID from the main response.

**Q: What if they don't expose retrieval evidence?**
If the client uses RAG internally but can't expose it, we fall back to `reference_context` from the scenario YAML -- static curated ground truth. Alternatively, RAG evaluation is skipped and we still run base conversation quality metrics.

**Q: What is separate evidence API?**
Some RAG systems log retrieved context to a trace/observability API. The chatbot response includes a `request_id`. We call `GET /trace/{request_id}` after each turn to fetch what was retrieved.

**Q: What if RAG API fails?**
EvalForge logs a warning and continues. RAG metrics are skipped for that turn. Base conversation metrics still run. Graceful degradation.

**Q: What is DeepEval?**
An open-source LLM evaluation framework providing standard metric classes (GEval, HallucinationMetric, etc.) that send prompts to a judge model and parse structured scores.

**Q: Which metrics do we use?**
Three base metrics (Goal Completion, Tone Adherence, Conversational Quality) always run. Three RAG metrics (Hallucination, Faithfulness, Answer Relevancy) run when retrieval evidence is available. Each returns 0.0-1.0 score and a human-readable reason.

**Q: Why normalization?**
EvalForge supports chatbot, voice, and calling channels. Normalization converts all of them to the same `NormalizedConversation` model before evaluation. The evaluation engine is completely unaware of the source channel.

**Q: Difference between voice and calling?**
Voice is real-time audio streaming (WebRTC, local microphone). Calling is telephone infrastructure (PSTN, SIP, Twilio). Voice sessions run while connected; calling involves asynchronous lifecycles with recordings and transcription after the call ends.

**Q: What information do we need from a client?**
For chatbot: endpoint URL, auth method, request/response field mapping. For RAG: retrieved context field path. For calling: provider name, credentials, phone numbers. For browser: the chatbot's URL and selectors.

**Q: Where are results stored?**
Evaluation results from `/test-runs` endpoint -> `eval_results.db` (SQLite). Agent connections -> `connections.db`. Calling connections -> `calling_connections.json`. Browser auth states -> `auth-state-{Name}.json` files. The new `/connections/{id}/evaluate` path currently returns results to frontend but does NOT save them to SQLite.

**Q: How do we protect credentials?**
`env:VAR_NAME` references keep secrets out of the database. API responses always blank credential values before returning. `AgentConnection.__repr__` omits the config dict. Error messages are sanitized. However, the system has no user authentication and uses SQLite -- development POC, not production-hardened.

**Q: What are current limitations?**
No user authentication, CORS fully open, SQLite only, WebSocket adapter stub-only, interactive engine disabled by default, inbound calling not end-to-end, non-Twilio/non-mock calling providers use mock runtime, new `/evaluate` results not persisted, browser sessions stored as unencrypted JSON files.

---

## PART 41: TECHNOLOGY SUMMARY TABLE

| Technology | Where Used | Vendor-Specific? | Replaceable? |
|-----------|-----------|-----------------|-------------|
| **Python 3.11/3.12** | Everything | No | No |
| **FastAPI 0.115** | `main.py`, all API files | No | Yes (Flask, Django) |
| **Pydantic v2** | All models and schemas | No | Yes (dataclasses) |
| **pydantic-settings** | `config.py` | No | Yes |
| **requests** | `adapters/chat/rest.py` | No | Yes (httpx) |
| **uvicorn** | Server | No | Yes (hypercorn) |
| **Playwright (async)** | `connections/browser_auth.py`, `adapters/chat/browser.py` | No | Yes (selenium) |
| **DeepEval 2.0.9** | `evaluator.py` | No | Yes (custom metrics) |
| **google-generativeai** | `evaluator.py:GeminiJudge` | Yes (Google) | Yes (any LLM) |
| **Groq** | `simulator.py`, `evaluator.py:GroqJudge` | Yes (Groq) | Yes (Ollama, OpenAI) |
| **Ollama** | `main.py:/mock-chat` | Optional | Yes |
| **SQLite** | `storage.py`, `connections/storage.py` | No | Yes (Postgres recommended for prod) |
| **PyYAML** | `main.py`, `connections/api.py` | No | Yes |
| **python-dotenv** | `config.py` | No | Yes |
| **sounddevice** | `voice/audio.py` | No | Yes |
| **faster-whisper** | `calling/providers/whisper.py` | No | Yes (OpenAI Whisper, cloud STT) |
| **piper-tts** | Voice subsystem | No | Yes (cloud TTS) |
| **HTML/CSS/JS (vanilla)** | `frontend/` | No | Yes (React/Vue) |

---

## PART 42: FINAL CHEAT SHEET

```
================================================================
                    EVALFORGE CHEAT SHEET
================================================================

PROJECT PURPOSE
---------------
Vendor-neutral AI agent evaluation platform.
Automated testing of ANY chatbot, voice agent, or calling agent.
No vendor lock-in. Pluggable adapters. LLM-based scoring.

MAIN FLOW
---------
Connection saved -> Scenario loaded -> ScenarioExecutor picks adapter ->
Groq simulates user -> Adapter contacts real chatbot ->
ConversationMessage + optional RAGEvidence per turn ->
EvaluationService -> DeepEval metrics (Groq judge) ->
EvaluationResult (scores + transcript)

TOP 10 FILES
------------
1.  app/main.py                      -- entry point, router registration
2.  app/schemas.py                   -- Persona, TestScenario, MetricResult
3.  app/models/conversation.py       -- RAGEvidence, ConversationMessage, NormalizedConversation
4.  app/connections/api.py           -- all connection + evaluation REST endpoints
5.  app/connections/registry.py      -- AdapterRegistry, adapter registration
6.  app/executor.py                  -- ScenarioExecutor, chatbot/voice dispatch
7.  app/simulator.py                 -- Groq user simulator
8.  app/adapters/chat/rest.py        -- RestChatAdapter (main chatbot adapter)
9.  app/rag.py                       -- RAG evidence extraction (dot-path)
10. app/evaluator.py                 -- DeepEval metrics, GroqJudge, GeminiJudge

CHATBOT FLOW (KEY FILES)
------------------------
POST /connections/{id}/evaluate (connections/api.py)
  -> ScenarioExecutor.execute()              (executor.py)
  -> AdapterRegistry.create()               (connections/registry.py)
  -> RestChatAdapter.__init__()             (adapters/chat/rest.py)
    -> _resolve_browser_token() if needed   (connections/browser_auth.py)
  -> loop: generate_next_user_turn()        (simulator.py -> Groq)
  -> loop: adapter.send_message()           (rest.py -> client chatbot)
         -> extract_rag_evidence()          (rag.py)
         -> ConversationMessage(rag_evidence)
  -> EvaluationService.evaluate()           (evaluation_service.py)
  -> evaluate_transcript()                  (evaluator.py -> DeepEval)
  -> EvaluationResult

RAG FLOW
--------
Mode 1 (same response):
  response.retrieved_chunks[].content -> extract_rag_evidence() -> RAGEvidence

Mode 2 (separate API):
  response.request_id -> GET /trace/{id} -> extract_rag_evidence() -> RAGEvidence

Evidence -> ConversationMessage.rag_evidence ->
_rag_evidence_by_turn() -> per-turn LLMTestCase ->
HallucinationMetric + FaithfulnessMetric + AnswerRelevancyMetric

No evidence -> rag_evaluation.status = "not_evaluated" -> base metrics still run

AI CALLING FLOW
---------------
POST /calling/connections/{id}/run (calling/ui_api.py)
  -> CallingEvaluationRuntimeRunner.run()   (calling/evaluation_runner.py)
  -> CallingEvaluationRunner.run_mock_call() (calling/runner.py)
  -> MockCallProvider.start_outbound_call() (calling/providers/mock.py)
  -> build_mock_transcript()               (calling/runner.py)
  -> EvidenceBuilder.build()               (calling/evidence_builder.py)
  -> ConversationNormalizer.normalize()     (calling/conversation_normalizer.py)
  -> call_transcript_to_normalized_conversation() (calling/normalizer.py)
  -> NormalizedConversation
  -> CallingEvaluationBridge.evaluate()    (calling/evaluation_bridge.py)
  -> EvaluationService.evaluate()          (evaluation_service.py)
  -> same DeepEval metrics as chatbot

CLIENT REQUIREMENTS
-------------------
For chatbot:      endpoint URL + request/response mapping + auth
For RAG:          context_path (same response) OR
                  correlation_path + evidence API URL (separate)
For browser:      chatbot URL + CSS selectors
For voice:        LiveKit server + credentials OR local audio hardware
For calling:      provider + credentials + phone numbers
For no client:    mock provider works for pipeline testing

TECH STACK
----------
Backend:   Python 3.11, FastAPI, Pydantic v2, requests, PyYAML
LLM:       Groq/Llama-3.1-8b (simulator + judge), Gemini (fallback)
Eval:      DeepEval 2.0.9
Browser:   Playwright (Chromium, async, dedicated thread)
Storage:   SQLite (connections.db, eval_results.db), JSON (calling)
Voice:     LiveKit, sounddevice, piper-tts, faster-whisper
UI:        Vanilla HTML/CSS/JS

IMPORTANT LIMITATIONS
---------------------
- No user authentication (dev POC only)
- WebSocket adapter: connect() is a stub -- not real WS
- Interactive engine disabled by default (enable_user_action_engine=False)
- Inbound calling: models exist, not end-to-end wired
- Non-Twilio/non-mock calling providers: config accepted, run uses mock
- New /evaluate path: results NOT persisted to SQLite
- Browser auth states: unencrypted JSON files on disk
- CORS: fully open (allow_origins=["*"])
- SQLite: single-file, not suitable for multi-user production

5 KEY ARCHITECTURAL DECISIONS
------------------------------
1. ADAPTER PATTERN: New chatbot vendors = new adapter class + 1 line in registry.
   AgentConnection model never changes.

2. GROQ SIMULATOR: Real LLM plays the user persona. Not scripted.
   Enables realistic, unpredictable conversations against real agents.

3. NORMALIZATION BOUNDARY: All channels (chatbot/voice/calling) produce
   NormalizedConversation. Evaluator never knows the source channel.

4. PER-TURN RAG EVIDENCE: RAGEvidence attaches to each ConversationMessage.
   Correlation with question guaranteed by same-turn extraction.
   Never leaked between turns.

5. BALANCED SCORE: base_avg + rag_avg equally weighted. Multiple RAG turns
   cannot dominate the overall score over conversation quality.

================================================================
```

---

*End of CODE_WALKTHROUGH.md -- Generated from current code as of October 2026.*
*All claims verified against actual source files. READ-ONLY ANALYSIS -- no code was modified.*
