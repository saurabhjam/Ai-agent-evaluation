# PROJECT_ARCHITECTURE.md
# AI Agent Evaluation Platform — Complete Engineering Handbook

> **IMPORTANT:** This document is based exclusively on the current codebase at `d:\bestQ\evalution-ai-agent`.
> Every claim is traceable to actual code. Where something is unconfirmed, it is explicitly marked.
> Do NOT modify any code based on this document. It is read-only documentation.

---

## TABLE OF CONTENTS

1. [Project Overview](#1-project-overview)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Project Structure — Folder Breakdown](#3-project-structure--folder-breakdown)
4. [File-by-File Documentation](#4-file-by-file-documentation)
5. [Chatbot Evaluation Flow — End-to-End](#5-chatbot-evaluation-flow--end-to-end)
6. [Voice Agent Flow](#6-voice-agent-flow)
7. [Scenario System](#7-scenario-system)
8. [Simulated User (Simulator)](#8-simulated-user-simulator)
9. [Connection System](#9-connection-system)
10. [Adapter Architecture](#10-adapter-architecture)
11. [Authentication Architecture](#11-authentication-architecture)
12. [Sophia AI — Case Study & Debugging Log](#12-sophia-ai--case-study--debugging-log)
13. [Frontend Architecture](#13-frontend-architecture)
14. [Report Generation](#14-report-generation)
15. [Database Architecture](#15-database-architecture)
16. [DeepEval Integration](#16-deepeval-integration)
17. [Implemented vs. Planned Features](#17-implemented-vs-planned-features)
18. [Future Architecture (Interactive Framework)](#18-future-architecture-interactive-framework)
19. [End-to-End Data Flow Diagrams](#19-end-to-end-data-flow-diagrams)
20. [Code Dependency Graph](#20-code-dependency-graph)
21. [Debugging Guide](#21-debugging-guide)
22. [New Engineer Onboarding](#22-new-engineer-onboarding)
23. [Manager Explanation (1-min / 5-min / 10-min)](#23-manager-explanation)

---

## 1. PROJECT OVERVIEW

### What is this project?

This is an **AI Agent Evaluation Platform** — a tool that automatically tests AI chatbots and voice agents by simulating real users, conducting conversations, and scoring the agent's performance using AI judges.

Think of it like a **QA robot** for AI systems. Instead of a human manually testing a chatbot, this platform sends a realistic simulated customer, runs a full conversation, and then grades how well the chatbot performed.

### Why was it built?

AI chatbots are notoriously hard to test. Traditional software testing checks if a button works or if a form submits. AI testing is different because:

- The same input can produce different outputs every time
- "Correct" is subjective (was the tone good? Did the bot really solve the problem?)
- Manual testing is slow and doesn't scale
- Most test frameworks test logic, not conversation quality

This platform was built to solve exactly that: **automated, repeatable, scored evaluation of AI agents.**

### Who will use it?

- **QA/Test engineers** who need to run regression testing on AI chatbots
- **AI engineers** who want to benchmark improvements to their models
- **Product managers** who want pass/fail reports on chatbot quality
- **Client companies** who want independent evaluation of their AI systems

### What problem does it solve?

| Problem | How This Platform Solves It |
|---|---|
| Manual chatbot testing is slow | Fully automated — simulated user conducts the entire conversation |
| AI responses are unpredictable | LLM-based judge scores conversations using structured rubrics |
| Different chatbots use different APIs | Adapter system abstracts away protocol differences (REST, WebSocket, Browser, etc.) |
| Hard to test authenticated endpoints | BrowserAuthManager handles login, cookies, JWT extraction |
| No standard for voice agent testing | Dedicated voice pipeline with STT/TTS, latency metrics, turn-taking analysis |
| No central dashboard | Full web UI with connection management, evaluation history, and metric reports |

### How is it different from other chatbot testing frameworks?

Most frameworks test chatbots by **comparing outputs to expected strings**. This platform is fundamentally different:

- **Simulated users** are driven by an LLM (Groq/llama-3.1-8b-instant) — they behave like a real person with a persona, goal, tone, and optional edge-case behaviors
- **Conversation is dynamic** — the simulated user responds to what the chatbot actually said, not a pre-scripted script
- **Scoring is semantic** — a Groq LLM judge (with Gemini fallback) evaluates quality dimensions, not string matching
- **Universal adapter system** — works with REST, WebSocket, Browser-automated UIs, LiveKit voice, and more without changing core code
- **Browser authentication** — can log into real websites using Playwright, capture session state, and reuse it across evaluations

### Current Implementation Status

| Layer | Status |
|---|---|
| REST chatbot evaluation (fake/real agents) | ✅ Fully implemented |
| Browser-based chatbot evaluation | ✅ Fully implemented |
| Browser authentication (OTP, Clerk, JWT) | ✅ Fully implemented |
| Multi-step REST protocol | ✅ Fully implemented |
| DeepEval LLM judge (Groq + Gemini) | ✅ Fully implemented |
| Web UI (connections, evaluations, scenarios) | ✅ Fully implemented |
| SQLite storage for runs and connections | ✅ Fully implemented |
| LiveKit voice adapter (WebRTC) | ✅ Implemented (tested in limited scenarios) |
| Local voice adapter (Piper TTS + Whisper STT) | ✅ Implemented |
| Voice-specific metrics (latency, turn-taking, etc.) | ✅ Implemented |
| WebSocket adapter | ⚠️ Stub only (returns hardcoded string) |
| Interactive framework (buttons, dropdowns, forms) | ⚠️ Data models only, not wired into execution |
| RAG-context faithfulness evaluation | ✅ Implemented (triggered by `rag_context` in scenario) |

---

## 2. HIGH-LEVEL ARCHITECTURE

### Complete System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              BROWSER (User's Web Browser)                               │
│                                                                                         │
│    ┌──────────────────────────────────────────────────────────────────────────────┐     │
│    │                   frontend/static/  (Single-Page App)                        │     │
│    │                                                                              │     │
│    │  index.html  ─── app.js ─── style.css                                       │     │
│    │                                                                              │     │
│    │  Pages: Dashboard | Connections | Evaluations | Scenarios | Settings         │     │
│    │  Modals: Add Connection | Run Evaluation | Paste Scenario                    │     │
│    └──────────────────┬───────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                         │  HTTP/JSON REST API calls
                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                          FASTAPI BACKEND  (app/)                                        │
│                                                                                         │
│  ┌──────────────┐   ┌───────────────────────────────────────────────────────────────┐  │
│  │  main.py     │   │           app/connections/api.py                              │  │
│  │  (Entry      │──▶│  GET/POST/PATCH/DELETE /connections                           │  │
│  │   point,     │   │  POST /connections/{id}/test                                  │  │
│  │   FastAPI,   │   │  POST /connections/{id}/evaluate  ◀── MAIN EVAL ENTRY POINT  │  │
│  │   lifespan)  │   │  POST /connections/browser-auth/start                         │  │
│  └──────────────┘   │  POST /connections/browser-auth/save                          │  │
│                     └────────────────────┬──────────────────────────────────────────┘  │
│                                          │                                              │
│                          ┌───────────────▼─────────────────────┐                       │
│                          │        ScenarioExecutor              │                       │
│                          │      (app/executor.py)               │                       │
│                          │  _execute_chatbot() / _execute_voice()│                      │
│                          └────────┬──────────────┬──────────────┘                       │
│                                   │              │                                      │
│           ┌───────────────────────▼──┐   ┌───────▼────────────────────┐                │
│           │     SIMULATOR            │   │   EVALUATION SERVICE        │                │
│           │  (app/simulator.py)      │   │   (app/evaluation_service.py│                │
│           │  Groq llama-3.1-8b       │   │   → app/evaluator.py        │                │
│           │  Generates user messages │   │   → app/voice/metrics.py)   │                │
│           └───────────────────────┬─┘   └───────┬────────────────────┘                │
│                                   │              │                                      │
│                    ┌──────────────▼──────────────┼──────────────────────┐              │
│                    │            ADAPTER LAYER                            │              │
│                    │                                                     │              │
│                    │  CHATBOT ADAPTERS     VOICE ADAPTERS                │              │
│                    │  ─────────────────    ─────────────────             │              │
│                    │  RestChatAdapter      LiveKitVoiceAdapter           │              │
│                    │  BrowserChatAdapter   LocalVoiceAdapter             │              │
│                    │  WebSocketAdapter     FakeVoiceAdapter              │              │
│                    │  FakeChatAdapter                                    │              │
│                    └──────────────────────┬──────────────────────────────┘              │
│                                          │                                              │
│   ┌──────────────────┐   ┌───────────────▼────────────────────────┐                    │
│   │   SQLite DB      │   │    BROWSER AUTH MANAGER                 │                    │
│   │  eval_results.db │   │   (app/connections/browser_auth.py)     │                    │
│   │                  │   │    Playwright + _PlaywrightThread        │                    │
│   │  Table: test_runs│   │    Session storage capture/restore      │                    │
│   │  Table: agent_   │   │    JWT interception                     │                    │
│   │    connections   │   └────────────────────────────────────────┘                    │
│   └──────────────────┘                                                                  │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                         │                         │
              ┌──────────▼──────────┐   ┌──────────▼──────────┐
              │   Groq API          │   │   Google Gemini API  │
              │   llama-3.1-8b      │   │   gemini-2.0-flash   │
              │   (Simulator +      │   │   (Judge fallback)   │
              │    Primary Judge)   │   │                      │
              └─────────────────────┘   └─────────────────────┘
                         │
              ┌──────────▼──────────────────────────────────┐
              │         EXTERNAL CHATBOT BEING TESTED        │
              │                                              │
              │  e.g., Sophia AI REST API                    │
              │  e.g., Any company chatbot                   │
              │  e.g., Your own mock /mock-chat endpoint     │
              └──────────────────────────────────────────────┘
```

### Two Execution Paths

There are two separate execution paths in the code:

```
PATH 1 — LEGACY (via main.py /test-runs)
  POST /test-runs
    → orchestrator.run_scenario()
    → AdapterFactory.create()   (app/adapters/factory.py)
    → simulator.generate_next_user_turn()
    → evaluator.evaluate_transcript()
    → storage.save_run()

PATH 2 — PRODUCTION (via connections/api.py /evaluate)
  POST /connections/{id}/evaluate
    → evaluate_connection()    (app/connections/api.py)
    → ScenarioExecutor.execute()  (app/executor.py)
    → ConnectionManager.create_adapter()  (app/connections/manager.py)
    → AdapterRegistry  (app/connections/registry.py)
    → EvaluationService.evaluate()  (app/evaluation_service.py)
    → storage.save_run()
```

The **production path** (Path 2) is what the UI uses. Path 1 still works but is considered legacy.

---

## 3. PROJECT STRUCTURE — FOLDER BREAKDOWN

```
d:\bestQ\evalution-ai-agent\
│
├── app/                          ← All Python backend code
│   ├── adapters/                 ← Protocol adapters (how we talk to agents)
│   │   ├── chat/                 ← Chatbot adapters
│   │   │   ├── base.py           ← Abstract ChatAdapter interface
│   │   │   ├── rest.py           ← REST API adapter (most complex, 634 lines)
│   │   │   ├── browser.py        ← Browser/Playwright adapter
│   │   │   ├── websocket.py      ← WebSocket adapter (stub)
│   │   │   └── fake.py           ← Fake/mock adapter for local testing
│   │   ├── voice/                ← Voice adapters
│   │   │   ├── base.py           ← Abstract VoiceAdapter interface
│   │   │   ├── livekit.py        ← LiveKit WebRTC voice adapter (540 lines)
│   │   │   ├── local.py          ← Local voice with Piper+Whisper (611 lines)
│   │   │   └── fake.py           ← Fake voice adapter for testing
│   │   └── factory.py            ← Legacy AdapterFactory (used by orchestrator)
│   │
│   ├── connections/              ← Universal Agent Connection System
│   │   ├── api.py                ← FastAPI router for /connections endpoints
│   │   ├── browser_auth.py       ← BrowserAuthManager (Playwright login flows)
│   │   ├── input.py              ← Client-facing AgentConnectionInput models
│   │   ├── manager.py            ← ConnectionManager (orchestrates adapter creation)
│   │   ├── parser.py             ← Translates AgentConnectionInput → AgentConnection
│   │   ├── registry.py           ← AdapterRegistry (maps names to adapter factories)
│   │   ├── result.py             ← ConnectionTestResult model
│   │   ├── service.py            ← Empty file (placeholder)
│   │   └── storage.py            ← ConnectionRepository (SQLite CRUD for connections)
│   │
│   ├── interactive/              ← Future interactive evaluation framework
│   │   ├── models.py             ← Data models only (not wired into execution)
│   │   ├── action_validator.py   ← Validates proposed user actions
│   │   ├── capability_registry.py ← Declares what each adapter can do
│   │   ├── conversation_state.py ← State model for future planner
│   │   └── response_understanding.py ← Parses agent responses for interactive elements
│   │
│   ├── models/                   ← Core data models
│   │   ├── connection.py         ← AgentConnection (internal connection model)
│   │   ├── conversation.py       ← ConversationMessage, NormalizedConversation
│   │   └── voice.py              ← VoiceConversation, VoiceTurn, VoiceEvent, etc.
│   │
│   ├── voice/                    ← Voice-specific evaluation logic
│   │   ├── audio.py              ← Audio utilities (trim silence, resample PCM)
│   │   ├── config.py             ← VoiceAdapterConfig, VoiceMetricsConfig models
│   │   ├── converter.py          ← VoiceConversation → NormalizedConversation
│   │   ├── metrics.py            ← Deterministic voice metrics (latency, turn-taking, etc.)
│   │   └── persona.py            ← VoicePersonaEngine (runs automated voice sessions)
│   │
│   ├── config.py                 ← Settings (Pydantic BaseSettings, reads .env)
│   ├── evaluation_service.py     ← EvaluationService (wraps evaluator + voice metrics)
│   ├── evaluator.py              ← DeepEval metrics + Groq/Gemini judge
│   ├── executor.py               ← ScenarioExecutor (main execution engine)
│   ├── main.py                   ← FastAPI app entry point
│   ├── orchestrator.py           ← Legacy run_scenario() function
│   ├── schemas.py                ← Pydantic models (TestScenario, Persona, MetricResult)
│   └── storage.py                ← save_run/get_run/list_runs for test_runs table
│
├── frontend/                     ← Web frontend (static files only)
│   ├── static/
│   │   ├── app.js                ← Entire Single Page App (1300 lines JavaScript)
│   │   └── style.css             ← CSS styles
│   └── index.html                ← Main HTML shell
│
├── scenarios/                    ← YAML scenario definition files
│   ├── refund_request.yaml       ← Demo scenario (fake adapter, e-commerce refund)
│   └── sophia_property_maintenance.yaml ← Real Sophia AI scenario
│
├── scripts/                      ← Utility, smoke test, and verification scripts
│   └── smoke_test_sophia.py      ← Manual smoke test for Sophia AI connection
│
├── .env.example                  ← Template for environment variables
├── .env                          ← Real secrets (not committed to git)
├── requirements.txt              ← Python package dependencies
├── README.md                     ← Project README (brief intro)
└── PROJECT_ARCHITECTURE.md       ← This file
```

### Why Each Folder Exists

| Folder | Why It Exists |
|---|---|
| `app/adapters/` | Each chatbot/voice agent uses a different protocol. Adapters isolate that complexity. |
| `app/connections/` | Manages persistent connection profiles for agents stored in the database. |
| `app/interactive/` | Foundation for future "interactive AI" evaluation (buttons, forms, dropdowns). |
| `app/models/` | Shared data structures used across the entire backend. |
| `app/voice/` | Voice agents need special handling (audio files, latency, STT/TTS). |
| `frontend/` | The web interface that non-engineers use to operate the platform. |
| `scenarios/` | YAML files that define what to test and how to test it. |
| `scripts/` | Standalone utility, smoke test, and verification scripts. |

---

## 4. FILE-BY-FILE DOCUMENTATION

### `app/main.py` — FastAPI Entry Point

**What it is:** The root of the FastAPI application. Every HTTP request starts here.

**Mounts:**
- `app/connections/api.py` router under `/connections`
- Serves the frontend (`frontend/static/`, `frontend/index.html`)

**Key routes defined directly in main.py:**

| Route | Purpose |
|---|---|
| `GET /health` | Returns `{"status":"ok"}`, used by frontend to check if backend is running |
| `GET /scenarios` | Scans `scenarios/` folder for `.yaml` files, returns list with id, channel, path |
| `POST /scenarios/validate` | Validates YAML content as a TestScenario without saving |
| `POST /scenarios/save` | Saves YAML text to `scenarios/` folder |
| `POST /mock-chat` | Local reference chatbot (powered by Gemini). Used to test the platform itself. |
| `POST /test-runs` | Legacy evaluation endpoint (uses orchestrator) |
| `GET /test-runs` | Lists all stored test run results |
| `GET /test-runs/{run_id}` | Gets a single stored test run |

**Lifespan hook (startup/shutdown):**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # On shutdown: close BrowserAuthManager (kills Playwright browser)
    await BrowserAuthManager.get_instance().close()
```

**Called by:** Everything. This is the entry point.

**Calls:** `app/connections/api.py`, `app/orchestrator.py`, `app/storage.py`

---

### `app/executor.py` — ScenarioExecutor (Production Engine)

**What it is:** The main evaluation engine used by the production path. Takes a `AgentConnection` and `TestScenario`, runs the conversation, and returns `ExecutionResult`.

**Key class:** `ScenarioExecutor`

**Key method:** `execute(connection, scenario)`:
1. Determines if chatbot or voice
2. Calls `_execute_chatbot()` or `_execute_voice()`
3. Returns `ExecutionResult(success, transcript, voice_conversation, error)`

**`_execute_chatbot()` flow:**
1. Creates adapter via `ConnectionManager.create_adapter(connection)`
2. Calls `adapter.connect()`
3. For each turn up to `max_turns`:
   - Calls `simulator.generate_next_user_turn(persona, transcript)`
   - Sends message to real chatbot via `adapter.send_message()`
   - Appends both turns to transcript
   - If `[END_CONVERSATION]` in user message → breaks loop
4. Calls `adapter.close()`
5. Returns transcript as `list[ConversationMessage]`

**Config merging:** The executor does a deep-merge of `scenario.agent.config` onto the base connection config. This allows scenario YAML to override specific adapter settings (e.g., endpoint, request_mapping fields).

**`_execute_voice()` flow:**
1. Creates voice adapter
2. Instantiates `VoicePersonaEngine`
3. Calls `persona_engine.run_automated_session()`
4. Returns `VoiceConversation`

**Called by:** `app/connections/api.py` → `evaluate_connection()`

**Calls:** `app/connections/manager.py`, `app/simulator.py`, `app/voice/persona.py`

---

### `app/connections/api.py` — Connections Router

**What it is:** The FastAPI router that handles all `/connections` endpoints. This is the primary interface between the frontend and the backend.

**Key routes:**

| Route | Purpose |
|---|---|
| `GET /connections` | List all saved connections from SQLite |
| `POST /connections` | Create new connection (parse, validate, test, save) |
| `GET /connections/{id}` | Get a single connection by ID |
| `PATCH /connections/{id}` | Update a connection (name, config, enabled) |
| `DELETE /connections/{id}` | Delete a connection |
| `POST /connections/{id}/test` | Test if a connection is reachable |
| `POST /connections/{id}/evaluate` | **Run a full evaluation** (MAIN PRODUCTION ENDPOINT) |
| `POST /connections/browser-auth/start` | Open a browser for interactive login |
| `POST /connections/browser-auth/save` | Save browser session state after login |

**`evaluate_connection()` (lines 246–311) — the most important function:**
1. Loads `AgentConnection` from SQLite by ID
2. Loads YAML scenario from file path
3. Parses scenario into `TestScenario`
4. Deep-merges connection config into scenario agent config
5. Calls `ScenarioExecutor.execute(connection, scenario)`
6. Calls `EvaluationService.evaluate(result, persona, scenario)` 
7. Saves result to `test_runs` SQLite table
8. Returns `TestRunResult` as JSON

**Called by:** Frontend via `API.evaluate(connId, scenPath)`

---

### `app/orchestrator.py` — Legacy Orchestrator

**What it is:** The original evaluation function before the Connection System was built.

**Key function:** `run_scenario(scenario, agent_override=None)`:
1. Merges agent config
2. Creates adapter via `AdapterFactory.create()`
3. Runs conversation loop using simulator
4. Runs DeepEval evaluation
5. Saves to SQLite
6. Returns `TestRunResult`

**Status:** Still works, but the production path uses `ScenarioExecutor` instead.

**Called by:** `app/main.py` `POST /test-runs`

---

### `app/evaluation_service.py` — Evaluation Service

**What it is:** Sits between the executor (which runs conversations) and the evaluator (which scores them). Handles both chatbot and voice evaluation.

**Key class:** `EvaluationService`

**Key method:** `evaluate(execution_result, persona, scenario)`:
1. Converts transcript (chatbot) or voice conversation (voice) into `list[ConversationMessage]`
2. Calls `evaluate_transcript(persona, transcript, rag_context)` from `app/evaluator.py`
3. For voice: also calls `run_voice_metrics(voice_conversation, config)` from `app/voice/metrics.py`
4. Computes `overall_score` = average of all metric scores
5. Determines `passed` = `overall_score >= pass_threshold`
6. Returns a dict with all fields needed to save to `test_runs` table

**Called by:** `app/connections/api.py` → `evaluate_connection()`

**Calls:** `app/evaluator.py`, `app/voice/metrics.py`, `app/voice/converter.py`

---

### `app/evaluator.py` — DeepEval Evaluation Engine

**What it is:** Contains the judge model classes and the main `evaluate_transcript()` function. This is where AI-powered scoring happens.

**Two judge model classes:**

**`GeminiJudge(DeepEvalBaseLLM)`:**
- Uses `google-generativeai` SDK
- Configured with `gemini_api_key` and `gemini_model` (default: `gemini-2.0-flash`)
- Forces JSON response via `response_mime_type="application/json"`
- Temperature: 0.5

**`GroqJudge(DeepEvalBaseLLM)`:**
- Uses `groq` Python SDK
- Configured with `groq_api_key` and `groq_model` (default: `llama-3.1-8b-instant`)
- Uses `json_object` response format
- Primary judge — Gemini is the fallback if Groq fails
- Has `self._fallback = GeminiJudge(...)` initialized lazily

**Default judge:** `get_judge()` always returns a `GroqJudge` instance (singleton). If Groq fails, it falls back to `GeminiJudge`.

**`evaluate_transcript(persona, transcript, rag_context)` function:**

Three metrics always run:

| Metric | DeepEval Class | What It Measures |
|---|---|---|
| Goal Completion | `GEval` | Did the agent actually solve the user's stated problem? |
| Persona and Tone Adherence | `GEval` | Did the agent stay professional and on-brand? |
| Conversational Quality | `ConversationalGEval` | Did the agent track context, understand intent, stay consistent? |

Three optional metrics run if `rag_context` is provided in the scenario:

| Metric | DeepEval Class | What It Measures |
|---|---|---|
| Hallucination | `HallucinationMetric` | Did the agent invent facts not in the context? (Score inverted: low hallucination = high score) |
| Answer Relevancy | `AnswerRelevancyMetric` | Was the answer relevant to the question? |
| Faithfulness | `FaithfulnessMetric` | Did answers stick to the provided context? |

**Threshold for all metrics:** 0.5 (pass if score >= 0.5)

**All metrics run synchronously** (`async_mode=False`) — one at a time, to avoid event loop conflicts.

**HallucinationMetric score inversion:** The raw Hallucination score measures how much the agent hallucinated (high = bad). The code inverts this: `normalized_score = 1.0 - raw_score`, so the final score is "how non-hallucinating" the agent was (high = good).

---

### `app/simulator.py` — Simulated User Generator

**What it is:** The "fake customer" engine. Given a persona and conversation history, generates what the simulated user would say next.

**Model used:** Groq `llama-3.1-8b-instant` (set in `settings.groq_model`)

**System prompt template:**
```
You are role-playing as a user talking to a customer support agent.

Persona name: {name}
Your goal: {goal}
Your tone: {tone}
{edge_case_line}

Rules:
- Speak ONLY as the user, in first person. Never break character.
- Never reveal you are an AI or that this is a test.
- Keep each message short and natural, like a real chat message (1-3 sentences).
- If the agent has fully satisfied your goal, respond with exactly: [END_CONVERSATION]
- Otherwise, react naturally to what the agent just said and push toward your goal.
```

**`generate_next_user_turn(persona, transcript)` function:**
1. Builds the system prompt with persona fields
2. Formats conversation history as `"You (user): ..." / "Agent: ..."` lines
3. Sends to Groq API with temperature=0.5, max_completion_tokens=256
4. Extracts `[ATTACHMENT: path/to/file]` tags from response (handles file attachments)
5. Suppresses duplicate attachments (each attachment only sent once per scenario)
6. Returns `{"message": text, "attachments": list_or_none}`

**`[END_CONVERSATION]` signal:** If the generated user message contains `[END_CONVERSATION]`, the executor stops the conversation loop early, treating the session as complete.

**Note:** The docstring says "Ollama" but the actual implementation uses **Groq**, not Ollama. The config file still has `ollama_base_url` and `ollama_model` settings that are not currently used by the simulator.

---

### `app/config.py` — Settings

**What it is:** All environment variable configuration, loaded from `.env` via Pydantic `BaseSettings`.

**All settings:**

| Setting | Default | Description |
|---|---|---|
| `gemini_api_key` | `""` | Gemini API key (judge model fallback) |
| `gemini_model` | `"gemini-2.0-flash"` | Gemini model name |
| `groq_api_key` | `""` | Groq API key (simulator + primary judge) |
| `groq_model` | `"llama-3.1-8b-instant"` | Groq model name |
| `ollama_base_url` | `"http://localhost:11434"` | Ollama URL (not used by current simulator) |
| `ollama_model` | `"llama3.1:8b"` | Ollama model (not used by current simulator) |
| `defect_generic_greeting_loop` | `False` | Seeded defect flag for testing the evaluator |
| `db_path` | `"./eval_results.db"` | SQLite database file path |
| `max_turns_per_run` | `12` | Maximum conversation turns allowed |
| `min_turns_per_run` | `2` | Minimum conversation turns allowed |

**Loaded from:** `PROJECT_ROOT/.env`

---

### `app/schemas.py` — API Validation Models

**What it is:** Pydantic models that validate every request before any LLM call is made.

**Models:**

**`Persona`:**
```python
name: str           # min_length=2, max_length=60
goal: str           # min_length=10, max_length=400
tone: str           # min_length=3, max_length=60
edge_case: Optional[str]  # max_length=300, optional adversarial behavior
```

**`AgentConfig`:**
```python
channel: str = "chatbot"   # "chatbot" or "voice"
adapter: str = "fake"      # adapter name
config: dict               # adapter-specific config
```

**`TestScenario`:**
```python
scenario_id: str            # min_length=3, max_length=80
agent: AgentConfig
persona: Persona
max_turns: int              # default=6, validated against settings bounds
pass_threshold: float       # default=0.7, 0.0-1.0
rag_context: Optional[list[str]]   # enables hallucination/faithfulness checks
agent_prompt: Optional[str]        # system prompt for fake/reference agent
```

**`MetricResult`:**
```python
name: str
score: float    # 0.0-1.0
reason: str
passed: bool
```

**`TestRunResult`:**
```python
run_id: str
scenario_id: str
agent: AgentConfig
transcript: list[Any]
metrics: list[MetricResult]
voice_metrics: Optional[list[MetricResult]]
overall_score: float
passed: bool
created_at: str
```

---

### `app/connections/browser_auth.py` — Browser Authentication Manager

**What it is:** Manages all browser-based authentication flows. Uses Playwright to open a real browser, let the user log in, capture cookies/localStorage/sessionStorage, and save it for reuse.

**Architecture constraint (Windows):** FastAPI uses `SelectorEventLoop`, but Playwright on Windows requires `ProactorEventLoop`. Solution: run Playwright in a dedicated daemon thread (`_PlaywrightThread`) with its own `ProactorEventLoop`.

**Key classes:**

**`_PlaywrightThread`:**
- Daemon thread with `asyncio.ProactorEventLoop()` on Windows
- Exposes `dispatch(coro) → concurrent.futures.Future` — lets synchronous code call async Playwright code

**`_BrowserAuthSession`:**
- Represents a single interactive login session
- Has `session_id`, reference to `Page` and `BrowserContext`
- Handles network interception (for JWT token extraction)

**`BrowserAuthManager` (singleton):**
- `start_browser_auth(url)` → opens Playwright browser, returns `session_id`
- `save_browser_auth(session_id, connection_name, ...)` → captures auth state, saves JSON file
- `extract_browser_token(storage_state_path, url, intercept_pattern, ...)` → reloads saved session, intercepts network request to capture JWT token

**SessionStorage gap (critical):**
Playwright's built-in `storage_state()` saves cookies + localStorage but **NOT** `window.sessionStorage`. This is a known Playwright limitation.

**Custom fix:**
- `_append_session_storage()`: Executes JavaScript to serialize `window.sessionStorage` into a custom key `_evalforge_sessionStorage` in the saved JSON file.
- On restore: `add_init_script()` injects a script that reads `_evalforge_sessionStorage` from the stored state and repopulates `window.sessionStorage` before the page JavaScript runs.

**Saved auth state file location:** `auth-state-{connection_name}.json` in the project root.

---

### `app/connections/storage.py` — Connection Repository

**What it is:** SQLite CRUD for the `agent_connections` table.

**`ConnectionRepository` class:**

| Method | SQL | Purpose |
|---|---|---|
| `save(connection)` | INSERT OR REPLACE | Save or update a connection |
| `get(id)` | SELECT | Get one connection by ID |
| `list_all()` | SELECT | Get all connections |
| `delete(id)` | DELETE | Remove a connection |

**Table columns:** `id`, `name`, `type`, `adapter`, `config_json`, `enabled`, `created_at`, `updated_at`

**JSON serialization:** The `config` dict is stored as JSON string in `config_json` column.

---

### `app/storage.py` — Test Run Storage

**What it is:** SQLite CRUD for the `test_runs` table.

| Method | Purpose |
|---|---|
| `save_run(result)` | Save evaluation result |
| `get_run(run_id)` | Retrieve single result |
| `list_runs()` | List all results (most recent first) |

**Table columns:** `run_id`, `scenario_id`, `agent_json`, `transcript_json`, `metrics_json`, `voice_metrics_json`, `overall_score`, `passed`, `created_at`

---

### `app/adapters/factory.py` — Legacy Adapter Factory

**What it is:** Original factory used by `orchestrator.py`. Maps adapter name string to adapter class.

**`AdapterFactory.create(agent_config)` → adapter instance:**
```python
"fake" → FakeChatAdapter
"rest" → RestChatAdapter
"websocket" → WebSocketChatAdapter
"browser" → BrowserChatAdapter
"livekit" → LiveKitVoiceAdapter
```

**Note:** The new system uses `AdapterRegistry` instead. This factory is kept for backward compatibility.

---

### `app/adapters/chat/rest.py` — REST Chat Adapter

**What it is:** The most complex adapter (634 lines). Handles REST API chatbots with many authentication modes and two protocol modes.

**Two protocol modes (determined at `__init__`):**

**Legacy mode** (when `send_config` OR `receive_config` is absent):
- Single POST request, response contains the reply

**Multi-step mode** (when both `send_config` AND `receive_config` are present):
- Step 1: POST to `send_url` to send user message
- Step 2: GET/POST to `receive_url` repeatedly until AI reply appears (polling)

**Auth resolution (happens at `__init__`, not per-request):**

| `auth.type` | What Happens |
|---|---|
| `browser_token` | Calls `_resolve_browser_token()` → runs Playwright headlessly to intercept JWT |
| `dynamic_rest` | Calls `_resolve_dynamic_rest()` → calls a login API endpoint to get a token |
| `bearer` | Sets `Authorization: Bearer {token}` header |
| `api_key` | Sets named header from `auth.header_name` with `auth.value` |
| `storage_state` | Restores Playwright cookies (for browser adapter use) |

**`_resolve_browser_token()` method:**
1. Reads `storage_state` path from config
2. Creates a `_PlaywrightThread`
3. Creates browser context with saved auth state
4. Navigates to `auth.url`
5. Sets up network interceptor matching `auth.intercept_pattern`
6. Waits for a matching request
7. Extracts token from `header:authorization` path (or other `token_path`)
8. Sets the extracted token as `Authorization: Bearer {token}` header
9. All future requests use this live JWT

**Request/Response mapping:**
Uses `get_by_path()` and `set_by_path()` helper functions that support dot-notation field access in nested JSON:
```python
"request_mapping": {"message_field": "question", "session_id_field": "conversation_id"}
"response_mapping": {"reply_field": "data.answer"}  # dot notation for nested fields
```

---

### `app/adapters/chat/browser.py` — Browser Chat Adapter

**What it is:** Uses Playwright to control a real browser, interact with a chatbot UI via CSS selectors, and extract responses from the DOM.

**Required config:**
- `url` or `base_url` — the webpage to open
- `selectors.input` — CSS selector for the input field
- `selectors.response` — CSS selector for agent response elements
- `selectors.submit` — CSS selector for send button (optional, Enter key can be used)
- `selectors.launcher` — CSS selector to open the chat widget (optional)

**Send/receive flow:**
1. Count existing response elements (`initial_count`)
2. Fill the input field with the user message
3. Click submit button or press Enter
4. Poll every 500ms until either:
   - A new response element appears (count increases), OR
   - The last response element's text changes
5. Return the new/changed text

**Thread architecture:** Same pattern as `BrowserAuthManager` — a `_BrowserThread` daemon thread with its own `ProactorEventLoop` to avoid `SelectorEventLoop` conflicts.

---

### `app/adapters/chat/fake.py` — Fake Chat Adapter

**What it is:** Calls the local `/mock-chat` endpoint (also a Gemini-powered chatbot in `main.py`) for testing. Used in all demo scenarios.

**Endpoint:** `http://localhost:8000/mock-chat` (configurable)

**Protocol:** POST `{"session_id": ..., "message": ..., "agent_prompt": ...}` → `{"reply": "..."}`

---

### `app/adapters/chat/websocket.py` — WebSocket Adapter

**What it is:** A stub/placeholder for WebSocket-based chatbots.

**Current state:** `connect()` logs but does nothing. `send_message()` always returns `"WebSocket response"`. Not functional.

---

### `app/adapters/voice/livekit.py` — LiveKit Voice Adapter

**What it is:** Connects to a LiveKit WebRTC room, streams audio using PCM, receives transcriptions from the voice agent.

**Key technical details:**
- Creates its own `asyncio.new_event_loop()` in a dedicated thread
- Uses `livekit` Python SDK for WebRTC connection
- Uses `PiperTTS` for text-to-speech synthesis
- Uses `FasterWhisperSTT` for transcribing agent audio responses
- Streams audio as raw PCM frames via LiveKit's audio track API

**`start_session()` flow:**
1. Creates LiveKit `Room`
2. Connects to LiveKit server with credentials
3. Publishes local audio track (microphone simulation)
4. Subscribes to agent audio track
5. Returns `session_id`

---

### `app/adapters/voice/local.py` — Local Voice Adapter

**What it is:** A local-only voice adapter that uses free open-source tools (no cloud services needed).

**Architecture:**
```
User text → PiperTTS → WAV file → HTTP POST to agent URL
Agent audio response → FasterWhisperSTT → agent text
```

**`FasterWhisperSTT`:** Uses `faster-whisper` library (local Whisper model). Supports sizes: tiny, small, base, medium, large. Device: cpu or cuda.

**`PiperTTS`:** Uses `piper-tts` library or `piper` binary. Requires `.onnx` voice model file. Default voice: `en_US-lessac-medium`.

**Agent communication:** Via HTTP POST with `multipart/form-data` (`audio` field containing WAV bytes). This assumes the voice agent under test accepts audio via HTTP.

---

### `app/voice/persona.py` — VoicePersonaEngine

**What it is:** Runs an automated voice session, taking turns as the simulated user.

**`run_automated_session()` flow:**
1. `adapter.start_session()` — start the voice call
2. Loop up to `max_turns`:
   - Get current transcript from adapter
   - Call `generate_next_user_turn(persona, transcript)` from simulator
   - If `[END_CONVERSATION]` → break
   - `tts.synthesize(user_text)` → WAV bytes
   - `adapter.send_audio(user_wav, turn_index)` — send to voice agent
   - `adapter.receive_audio(timeout_seconds)` — wait for agent response
3. `adapter.end_session()` → returns `VoiceConversation`

**`generate_full_audio_and_json()` static method:**
- Merges all WAV files into a single `full_conversation.wav` with 300ms silence between turns
- Resamples audio to 16000 Hz target
- Saves `conversation.json` with turn details and audio paths

---

### `app/voice/metrics.py` — Voice Metrics

**What it is:** Six deterministic (non-LLM) metrics for voice evaluation.

| Metric | Logic |
|---|---|
| `evaluate_latency()` | Avg/max agent response latency in ms, compared to `warning_ms`/`failure_ms` thresholds |
| `evaluate_turn_taking()` | Checks for invalid sequences (agent speaking 3+ consecutive turns) |
| `evaluate_interruption()` | Counts `VoiceTurn.interrupted=True` turns, compares to `max_allowed` |
| `evaluate_silence()` | Finds max gap between consecutive events, compares to `max_gap_ms` |
| `evaluate_audio_evidence()` | Verifies WAV files exist for all expected turns |
| `evaluate_session_completion()` | Checks that `VoiceSession` has `started_at`, `ended_at`, and `status=completed` |

All return `MetricResult` with `score` = 1.0 (pass) or 0.0 (fail) — binary pass/fail, no partial scores.

---

### `app/connections/manager.py` — Connection Manager

**What it is:** Provider-neutral gateway between an `AgentConnection` and a concrete adapter.

**`test_connection(connection)` flow:**
1. Check `connection.enabled` → return `disabled` result if False
2. Check `AdapterRegistry.has(type, adapter_name)` → return `unknown_adapter` if not found
3. `registry.create(connection)` → instantiate adapter (catches import/config errors)
4. Call `adapter.connect()` → probe connectivity
5. Return `ConnectionTestResult.connected(...)` on success

**`create_adapter(connection)` method:** Like test_connection but raises exceptions instead of returning error results.

**`_sanitise_error_message()`:** Redacts `key=`, `secret=`, `token=`, `password=` patterns from error messages to prevent credential leakage in logs.

---

### `app/connections/parser.py` — Connection Input Parser

**What it is:** Translates `AgentConnectionInput` (client-facing) into `AgentConnection` (internal).

**`parse_connection_input(agent_input)` config assembly order:**
1. URL → mapped to adapter-specific key (`base_url`, `server_url`)
2. Auth → stored as `{"type": ..., "value": ...}` in config
3. CSS selectors → stored as `config["selectors"]` dict
4. Extra options → merged last (client can override anything)

**Special browser_token handling (lines 124–130):**
Fields `browser_login_url`, `intercept_pattern`, `token_path`, `header_name`, `header_format` are moved from `options` into the `auth` dict so `RestChatAdapter` finds them in the right place.

---

### `app/connections/registry.py` — Adapter Registry

**What it is:** Maps `(agent_type, adapter_name)` → factory callable.

**Currently registered adapters:**

Chatbot:
- `rest` → `RestChatAdapter`
- `websocket` → `WebSocketChatAdapter`
- `browser` → `BrowserChatAdapter`
- `fake` → `FakeChatAdapter`

Voice:
- `livekit` → `LiveKitVoiceAdapter`
- `fake` → `FakeVoiceAdapter`
- `local` → `LocalVoiceAdapter`

**Not registered** (not implemented): `sse`, `sip`, `phone`, `webrtc`, `custom`

**Lazy imports:** Adapter classes are imported only when `registry.create()` is called, so missing optional dependencies (like `livekit`) don't break the rest of the app.

---

### `app/connections/input.py` — Client-Facing Input Models

**What it is:** Pydantic models that a client (user, UI form, API caller) provides to connect an agent.

**Validation rules:**
- `name` must be non-empty
- `type` must be `"chatbot"` or `"voice"`
- `method` must be compatible with `type` (e.g., `livekit` only for voice)
- URL is required for all network methods (`rest`, `websocket`, `browser`, `livekit`)

**`AuthConfig`** fields: `type` (scheme name) and `value` (the secret). The `__repr__` hides `value` to prevent credential logging.

**`BrowserSelectors`** fields: `input`, `submit`, `response`, `launcher` (CSS selectors for browser adapter).

---

### `app/models/connection.py` — AgentConnection (Internal Model)

**What it is:** The internal representation of a connection, used throughout the framework.

**Fields:** `id`, `name`, `type` (AgentType enum), `adapter` (free-form string), `config` (dict), `enabled` (bool)

**`__repr__` hides `config`** to prevent credential logging in tracebacks.

---

### `app/models/conversation.py` — Conversation Models

**`ConversationMessage`:**
- `role`: `"simulated_user"`, `"agent"`, or `"system"`
- `content`: the text of the message
- `turn_index`: turn number in conversation
- `timestamp`: ISO 8601 string
- `tool_calls`: optional list of `ToolCallInfo`
- `attachments`: optional list of file paths
- `metadata`: optional dict

**`NormalizedConversation`:** Top-level container:
- `run_id`, `session_id`, `channel`
- `messages: list[ConversationMessage]`
- `retrieval_context`, `start_time`, `end_time`, `status`, `metadata`

---

### `app/models/voice.py` — Voice Models

**`VoiceTurn`:** Single utterance — `speaker` (user/agent/system), `text`, `timestamp`, `latency_ms`, `audio_path`, `interrupted`

**`VoiceEvent`:** Discrete event — `event_type` (call_started, speech_started, interruption, etc.), `timestamp`, `data`

**`VoiceSession`:** Call metadata — `session_id`, `call_id`, `started_at`, `ended_at`, `status`

**`VoiceConversation`:** Complete call evidence — `session`, `turns`, `events`, `tool_calls`, `tool_results`, `handoff_events`

**Helper methods on `VoiceConversation`:**
- `user_turns()`, `agent_turns()`, `interruptions()`
- `average_agent_latency_ms()`, `duration_seconds()`

---

### `app/interactive/` — Future Interactive Framework

**What it is:** A foundation for evaluating chatbots that use interactive UI elements (buttons, dropdowns, quick replies, etc.). Currently data models and validators only — **not wired into any execution path**.

**`models.py`:**
- `InteractiveElementType`: button, quick_reply, dropdown_option, card, form, upload_request, confirmation, date_picker, time_picker, link, etc.
- `ActionType`: send_text, click_option, click_button, select_dropdown, upload_file, upload_document, select_date, select_time, dtmf, wait, open_link
- `UserAction`: proposed action from the simulated user
- `NormalizedAgentResponse`: parsed agent response with `interactive: list[InteractiveElement]`
- `ActionValidationResult`: validation outcome

**`action_validator.py`:** `ActionValidator.validate(action, adapter_name)` — checks shape (e.g., SEND_TEXT requires text) and capability support.

**`capability_registry.py`:** Declares which action types each adapter "supports" (declaratively, Phase 1 only):
- `rest, browser, websocket, fake` → support `send_text, click_option, click_button`
- `livekit, local` → support `send_text, wait, dtmf`

**`conversation_state.py`:** `ConversationState` data class — tracks goals, known facts, missing facts, conversation memory. For future planner use.

**`response_understanding.py`:** `ResponseUnderstanding.normalize()` — parses adapter metadata or plain text to extract interactive elements. Falls back to heuristic parsing of bullet/numbered lists in plain text.

---

## 5. CHATBOT EVALUATION FLOW — END-TO-END

This traces **exactly** what happens when a user clicks "Evaluate" on the frontend.

```
USER clicks "Evaluate" button on Connections page
    │
    ▼
App.openEvalModal(connId)           [frontend/static/app.js line 775]
    │ Fetches connection details, loads available scenarios
    │
    ▼
App.runEvaluation()                  [app.js line 834]
    │ Validates scenario selection
    │ Calls API.evaluate(connId, scenPath)
    │
    ▼ HTTP POST /connections/{connId}/evaluate?scenario_path={scenPath}
    │
    ▼
evaluate_connection(id, scenario_path)  [app/connections/api.py line 246]
    │
    ├─ 1. Load AgentConnection from SQLite
    │        ConnectionRepository.get(id)  → AgentConnection
    │
    ├─ 2. Load scenario YAML from file
    │        yaml.safe_load(Path(scenario_path).read_text())
    │
    ├─ 3. Parse scenario into TestScenario
    │        TestScenario(**yaml_data)   [app/schemas.py]
    │        → Validates: max_turns, pass_threshold, persona.goal, etc.
    │
    ├─ 4. Deep-merge connection.config into scenario.agent.config
    │        scenario.agent.config = {**connection.config, **scenario.agent.config}
    │
    ├─ 5. Run execution
    │        ScenarioExecutor().execute(connection, scenario)
    │
    │    ┌──────────── ScenarioExecutor._execute_chatbot() ─────────────────┐
    │    │                                                                   │
    │    │  a. ConnectionManager.create_adapter(connection)                  │
    │    │     → AdapterRegistry.create(connection)                          │
    │    │     → Lazily imports RestChatAdapter (or other)                   │
    │    │     → RestChatAdapter.__init__(config)                            │
    │    │         → Resolves auth (browser_token, bearer, api_key, etc.)    │
    │    │         → Sets HTTP headers for all future requests               │
    │    │                                                                   │
    │    │  b. adapter.connect()                                             │
    │    │     → For REST: tests HTTP connectivity to endpoint               │
    │    │     → For Browser: opens Playwright browser, loads page           │
    │    │                                                                   │
    │    │  c. CONVERSATION LOOP (up to max_turns):                          │
    │    │     Turn 1:                                                        │
    │    │       generate_next_user_turn(persona, [])                         │
    │    │       → Groq API: llama-3.1-8b generates first user message       │
    │    │       → Returns {"message": "Hi, I need...", "attachments": null} │
    │    │                                                                   │
    │    │       adapter.send_message("Hi, I need...")                       │
    │    │       → POST to chatbot endpoint with message                     │
    │    │       → Returns chatbot's reply text                              │
    │    │                                                                   │
    │    │       transcript = [                                               │
    │    │         ConversationMessage(role="simulated_user", content="Hi..") │
    │    │         ConversationMessage(role="agent", content="Hello! How..")  │
    │    │       ]                                                           │
    │    │                                                                   │
    │    │     Turn 2:                                                        │
    │    │       generate_next_user_turn(persona, transcript)                 │
    │    │       → Groq sees full conversation history                       │
    │    │       → Generates contextually appropriate next message           │
    │    │       ...                                                         │
    │    │                                                                   │
    │    │     [END_CONVERSATION] check: if user message contains this       │
    │    │     magic token → break loop early (goal completed)               │
    │    │                                                                   │
    │    │  d. adapter.close()                                               │
    │    │  e. Return ExecutionResult(success=True, transcript=[...])        │
    │    └───────────────────────────────────────────────────────────────────┘
    │
    ├─ 6. Evaluate transcript
    │        EvaluationService.evaluate(execution_result, persona, scenario)
    │
    │    ┌──────────── evaluate_transcript() [app/evaluator.py] ─────────────┐
    │    │                                                                    │
    │    │  Build LLMTestCase:                                                │
    │    │    input = "User goal: {goal}\nUser persona: {name} ({tone})"      │
    │    │    actual_output = full conversation text as "User: / Agent:" lines │
    │    │    context = rag_context or ["No specific context provided."]       │
    │    │                                                                    │
    │    │  Build ConversationalTestCase (for ConversationalGEval):           │
    │    │    turns = [{input: user_msg, actual_output: agent_msg}, ...]       │
    │    │                                                                    │
    │    │  For each metric in [GoalCompletion, ToneAdherence, ConvQuality]:  │
    │    │    metric.measure(test_case)  → calls Groq judge via DeepEval      │
    │    │    Groq returns JSON score + reason                                 │
    │    │    results.append(MetricResult(name, score, reason, passed))        │
    │    │                                                                    │
    │    │  If rag_context: also run Hallucination, Relevancy, Faithfulness   │
    │    │  Return list[MetricResult]                                         │
    │    └────────────────────────────────────────────────────────────────────┘
    │
    ├─ 7. Compute overall_score = mean of all metric scores
    │      passed = overall_score >= pass_threshold (default 0.7)
    │
    ├─ 8. Save to SQLite
    │        storage.save_run(result)  → INSERT into test_runs
    │
    ├─ 9. Return TestRunResult JSON to frontend
    │
    ▼
Frontend: API.evaluate() resolves with result
    │
    ▼
State.evaluations.push(result)          [app.js line 857]
App.navigate("eval-details", result)    [app.js line 859]
    │
    ▼
App.renderEvalDetails(result)           [app.js line 922]
    │ Renders: agent header, score cards, conversation transcript, metric cards
    │
    ▼
DONE — user sees evaluation report
```

---

## 6. VOICE AGENT FLOW

### Current Voice Architecture

Voice evaluation is fully implemented for LiveKit and LocalVoiceAdapter. Below is the complete flow.

```
User clicks "Evaluate" on a Voice connection
    │
    ▼  (Same frontend path as chatbot, different adapter)
evaluate_connection()  [app/connections/api.py]
    │
    ▼
ScenarioExecutor._execute_voice()  [app/executor.py]
    │
    ├─ Create voice adapter via ConnectionManager
    │    → LiveKitVoiceAdapter(config) or LocalVoiceAdapter(config)
    │
    ├─ Create VoicePersonaEngine:
    │    persona_engine = VoicePersonaEngine(
    │        persona=scenario.persona,
    │        adapter=voice_adapter,
    │        tts_provider=PiperTTS(...),
    │        max_turns=scenario.max_turns
    │    )
    │
    ├─ persona_engine.run_automated_session()
    │
    │  ┌──────────── VoicePersonaEngine.run_automated_session() ───────────┐
    │  │                                                                    │
    │  │  session_id = adapter.start_session()                              │
    │  │    → LiveKit: connects to room, publishes audio track              │
    │  │    → Local: creates session dir, records start timestamp           │
    │  │                                                                    │
    │  │  Turn loop (up to max_turns):                                       │
    │  │    1. transcript = adapter.get_transcript()                         │
    │  │                                                                    │
    │  │    2. user_text = generate_next_user_turn(persona, transcript)      │
    │  │         → Groq API generates user's next message                   │
    │  │         → If [END_CONVERSATION] → break                            │
    │  │                                                                    │
    │  │    3. user_wav = tts.synthesize(user_text)                          │
    │  │         → PiperTTS.synthesize(text)                                │
    │  │         → Returns WAV bytes (16-bit mono PCM)                      │
    │  │                                                                    │
    │  │    4. adapter.send_audio(user_wav, turn_index)                      │
    │  │         LiveKit: streams PCM frames via WebRTC audio track          │
    │  │         Local: saves WAV file, runs STT on it, records VoiceTurn   │
    │  │                                                                    │
    │  │    5. adapter.receive_audio(timeout_seconds=30)                     │
    │  │         LiveKit: waits for agent audio frames, saves to WAV,        │
    │  │                  runs FasterWhisperSTT to get text                  │
    │  │         Local: HTTP POST to agent_url, gets agent audio,            │
    │  │                runs FasterWhisperSTT to get text                    │
    │  │                                                                    │
    │  │  voice_conversation = adapter.end_session()                         │
    │  │    → VoiceConversation(session, turns, events, ...)                │
    │  └────────────────────────────────────────────────────────────────────┘
    │
    ├─ EvaluationService.evaluate(result, persona, scenario)
    │    │
    │    ├─ Voice metrics (deterministic, no LLM):
    │    │    run_voice_metrics(voice_conversation, VoiceMetricsConfig())
    │    │    → 6 metrics: latency, turn_taking, interruption, silence,
    │    │                 audio_evidence, session_completion
    │    │
    │    ├─ Convert voice to chat format:
    │    │    voice_converter.to_normalized_conversation(voice_conversation)
    │    │    → Maps VoiceTurn.speaker → ConversationMessage.role
    │    │
    │    └─ LLM metrics (same as chatbot):
    │         evaluate_transcript(persona, chat_transcript, rag_context)
    │         → GoalCompletion, ToneAdherence, ConversationalQuality
    │
    ├─ Compute overall_score, passed
    ├─ Save to SQLite (test_runs)
    └─ Return result to frontend
```

### Voice Metrics Detail

| Metric | Implemented | How |
|---|---|---|
| Response Latency | ✅ | `VoiceTurn.latency_ms` compared to 1500ms warning / 5000ms failure |
| Turn Taking | ✅ | Checks for agent taking 3+ consecutive turns |
| Interruptions | ✅ | Counts `VoiceTurn.interrupted=True` |
| Silence Gaps | ✅ | Max gap between consecutive `VoiceEvent` timestamps |
| Audio Evidence | ✅ | Verifies WAV files exist for all turns |
| Session Completion | ✅ | Checks session has proper timestamps and status |

### Voice Components File Map

| Component | File | Purpose |
|---|---|---|
| LiveKit adapter | `app/adapters/voice/livekit.py` | WebRTC connection to real LiveKit room |
| Local adapter | `app/adapters/voice/local.py` | HTTP + Piper TTS + Whisper STT |
| Fake adapter | `app/adapters/voice/fake.py` | For unit testing, returns mock responses |
| FasterWhisperSTT | `app/adapters/voice/local.py` | Speech-to-text (local, free) |
| PiperTTS | `app/adapters/voice/local.py` | Text-to-speech (local, free) |
| Persona engine | `app/voice/persona.py` | Runs automated session loop |
| Voice metrics | `app/voice/metrics.py` | 6 deterministic metrics |
| Voice config | `app/voice/config.py` | Configuration models |
| Voice data models | `app/models/voice.py` | VoiceConversation, VoiceTurn, etc. |
| Voice converter | `app/voice/converter.py` | VoiceConversation → NormalizedConversation |
| Audio utilities | `app/voice/audio.py` | Trim silence, resample PCM |

---

## 7. SCENARIO SYSTEM

### What is a Scenario?

A scenario is a YAML file in the `scenarios/` folder that defines exactly what to test and how to test it. Think of it as a test case definition.

### Scenario YAML Structure

**Full example (`scenarios/refund_request.yaml`):**
```yaml
scenario_id: refund_request_v1          # Unique identifier
agent:
  channel: chatbot                      # "chatbot" or "voice"
  adapter: fake                         # adapter type

persona:
  name: "Priya"                         # Simulated user's name
  goal: "Get a refund for a damaged order #A1029"  # What they want to accomplish
  tone: "polite but increasingly impatient"         # How they behave
  edge_case: "mentions order number only if asked"  # Optional adversarial behavior

max_turns: 6                            # Maximum conversation exchanges
pass_threshold: 0.7                     # Minimum score to "pass" (0.0-1.0)

rag_context:
  - "Refund policy: damaged orders are eligible for full refund within 30 days."
  # Adding this enables Hallucination, Relevancy, Faithfulness metrics

agent_prompt: |
  You are a helpful customer support agent.
  Handle: damaged order refunds, replacements.
  Follow the supplied refund policy.
  # Only used for fake adapter (Gemini-powered reference agent)
```

**Real Sophia AI scenario (`scenarios/sophia_property_maintenance.yaml`):**
```yaml
scenario_id: sophia_property_maintenance_v1
agent:
  channel: chatbot
  adapter: rest

persona:
  name: "Alex"
  goal: "Report a water leak in unit 204 and get a maintenance request confirmed"
  tone: "concerned property manager, clear and direct"

max_turns: 8
pass_threshold: 0.65
```

### How Scenarios Are Loaded

1. Frontend calls `GET /scenarios` → scans `scenarios/*.yaml`, returns list of `{id, channel, path}`
2. User selects a scenario in the Evaluate modal
3. Frontend sends `POST /connections/{id}/evaluate?scenario_path=scenarios/sophia_property_maintenance.yaml`
4. Backend: `yaml.safe_load(Path(scenario_path).read_text())`
5. Parsed into `TestScenario(**yaml_data)` — Pydantic validates all fields

### Persona Fields Explained

| Field | Required | What The Simulator Does With It |
|---|---|---|
| `name` | Yes | Used in the system prompt (e.g., "Persona name: Priya") |
| `goal` | Yes | Core objective. Simulator pushes toward this every turn. |
| `tone` | Yes | How the simulated user speaks. Included in system prompt. |
| `edge_case` | No | Added as "Edge-case behavior to weave in: ..." to system prompt |

### How Conversation Ends

Three ways the conversation can end:
1. **Max turns reached** — `turn_count >= max_turns`
2. **[END_CONVERSATION] signal** — Simulator returns this when goal is satisfied
3. **Adapter error** — Network timeout, auth failure, etc.

---

## 8. SIMULATED USER (SIMULATOR)

### What The Simulator Actually Does

The simulator is `app/simulator.py`. It's 130 lines that call the Groq API to generate realistic user messages.

### Prompt Construction

The system prompt has two parts:

**System message** (role: "system"):
```
You are role-playing as a user talking to a customer support agent.

Persona name: {name}
Your goal: {goal}
Your tone: {tone}
Edge-case behavior to weave in: {edge_case}   # Only if edge_case is set

Rules:
- Speak ONLY as the user, in first person. Never break character.
- Never reveal you are an AI or that this is a test.
- Keep each message short and natural (1-3 sentences).
- If the agent has fully satisfied your goal, respond with exactly: [END_CONVERSATION]
- Otherwise, react naturally and push toward your goal.
```

**User message** (role: "user"):
```
Conversation so far:
You (user): Hello, I need help
Agent: Hi! How can I assist you today?
You (user): I placed an order that arrived damaged...

Your next message:
```

### API Call Parameters

```python
client = Groq(api_key=settings.groq_api_key)
response = client.chat.completions.create(
    model=settings.groq_model,              # "llama-3.1-8b-instant"
    messages=messages,
    temperature=0.5,                        # Semi-random (not fully deterministic)
    max_completion_tokens=256,              # Short messages only
    reasoning_effort="low",                # Speed over quality for generation
    include_reasoning=False,
    timeout=10.0                            # 10 second timeout
)
```

### Attachment Handling

The simulator can include `[ATTACHMENT: path/to/file]` tags in messages. These are:
1. Extracted via regex from the generated text
2. Deduplicated (each attachment only sent once per scenario)
3. Stripped from the final text
4. Passed as `attachments` list in the return dict

### Note on Ollama

The file docstring says "Ollama" but the actual implementation uses **Groq**. The `settings.ollama_base_url` and `settings.ollama_model` config keys exist but are NOT used by the current `generate_next_user_turn()` function.

---

## 9. CONNECTION SYSTEM

### What Is A "Connection"?

A connection is a saved profile that tells the platform how to reach a specific chatbot or voice agent. It's stored in the SQLite database.

Think of it like a "saved contact" — you save the URL, auth method, and settings once, then select it whenever you want to run an evaluation.

### The Four-Layer Connection Architecture

```
CLIENT INPUT                 INTERNAL                REGISTRY              ADAPTER
─────────────────────────    ─────────────────────    ─────────────────    ─────────────────────
AgentConnectionInput         AgentConnection          AdapterRegistry      RestChatAdapter
  name                    →    id                  →   (type, name)     →  BrowserChatAdapter
  type                         name                     factory             LiveKitVoiceAdapter
  connection:                  type (enum)                                  FakeChatAdapter
    method                     adapter (string)                             ...
    url                        config (dict)
    auth                       enabled
    options
    selectors

   input.py                 models/connection.py      registry.py          adapters/*/
   (client-facing)          (internal model)          (factory map)        (concrete)

                  ↑                         ↑
            parser.py              manager.py
          (translates)            (orchestrates)
```

### Connection Lifecycle

**1. User fills out Add Connection modal (frontend)**
↓
**2. `API.createConnection(payload)` → `POST /connections`**
↓
**3. `create_connection_route()` in `api.py`:**
- Parses `AgentConnectionInput` (Pydantic validates)
- `parse_connection_input()` → `AgentConnection`
- `ConnectionManager.test_connection()` → tries to reach the agent
- `ConnectionRepository.save()` → persists to SQLite
- Returns the saved connection as JSON
↓
**4. Connection appears in Connections table**

**5. User clicks "Test" → `POST /connections/{id}/test`:**
- `ConnectionManager.test_connection()` → live connectivity check
- Returns `ConnectionTestResult(success, status, message)`

**6. User clicks "Evaluate" → Full eval flow (Section 5)**

### Connection Config Dict Keys

The `config` dict in `AgentConnection` is adapter-specific. Common keys:

| Key | Used By | Meaning |
|---|---|---|
| `base_url` | REST, Browser, WebSocket | Base URL of the agent |
| `endpoint` | REST | Full endpoint URL for single-step mode |
| `server_url` | LiveKit | LiveKit server URL |
| `auth.type` | REST | Auth scheme: `bearer`, `api_key`, `browser_token`, `dynamic_rest` |
| `auth.value` | REST | Auth credential |
| `auth.url` | REST browser_token | Login URL to open in headless browser |
| `auth.intercept_pattern` | REST browser_token | URL pattern to intercept for token |
| `auth.token_path` | REST browser_token | Where in request to find token (e.g., `header:authorization`) |
| `auth.header_name` | REST | HTTP header to set |
| `auth.header_format` | REST | Format string: `"Bearer {token}"` |
| `storage_state` | REST, Browser | Path to Playwright session state JSON |
| `request_mapping` | REST | Maps fields in outgoing request |
| `response_mapping` | REST | Maps fields in response to extract reply |
| `selectors.input` | Browser | CSS selector for chat input |
| `selectors.response` | Browser | CSS selector for agent response |

### ConnectionTestResult Statuses

| Status | Meaning |
|---|---|
| `connected` | Successfully reached the agent |
| `failed` | Network/transport error |
| `disabled` | Connection is disabled (`enabled=False`) |
| `configuration_error` | Missing/invalid adapter config |
| `unknown_adapter` | Adapter name not registered |
| `unsupported` | Adapter doesn't support this agent type |

---

## 10. ADAPTER ARCHITECTURE

### Adapter Hierarchy

```
ChatAdapter (abstract, app/adapters/chat/base.py)
    │
    ├── FakeChatAdapter      (app/adapters/chat/fake.py)     ← POST /mock-chat
    ├── RestChatAdapter      (app/adapters/chat/rest.py)     ← REST/multi-step/browser_token
    ├── BrowserChatAdapter   (app/adapters/chat/browser.py)  ← Playwright DOM automation
    └── WebSocketChatAdapter (app/adapters/chat/websocket.py) ← Stub, not functional

VoiceAdapter (abstract, app/adapters/voice/base.py)
    │
    ├── FakeVoiceAdapter     (app/adapters/voice/fake.py)    ← Test only
    ├── LiveKitVoiceAdapter  (app/adapters/voice/livekit.py) ← WebRTC via LiveKit
    └── LocalVoiceAdapter    (app/adapters/voice/local.py)   ← Piper TTS + Whisper STT
```

### ChatAdapter Required Methods

```python
connect()                     # Establish connection to agent
send_message(message, agent_prompt, attachments) → str  # Send message, return reply
get_transcript() → list[ConversationMessage]    # Get conversation history
get_conversation() → NormalizedConversation     # Get full conversation object
close()                       # Clean up resources
```

### VoiceAdapter Required Methods

```python
start_session(config) → str       # Start voice session, return session_id
end_session() → VoiceConversation # End session, return full conversation evidence
send_audio(audio_bytes, turn_index)   # Send user audio
receive_audio(timeout_seconds) → bytes # Wait for and return agent audio
get_transcript() → list[VoiceTurn]    # Current conversation turns
```

### Adapter Lifecycle in Production

```
1. registry.create(connection)       → __init__(config)
      ↓
2. adapter.connect()                 → test connectivity
      ↓
3. for each turn:
      simulator → user_message
      adapter.send_message(user_message) → agent_reply
      ↓
4. adapter.close()                   → cleanup
```

### RestChatAdapter — Auth Flow Detail

```
__init__(config)
    │
    ├── auth.type == "browser_token"?
    │     → _resolve_browser_token()
    │         → Load storage_state JSON
    │         → Start Playwright thread
    │         → Create browser context (with saved cookies/localStorage)
    │         → Navigate to auth.url
    │         → Set network interceptor (pattern: auth.intercept_pattern)
    │         → Wait for first matching request
    │         → Extract token from request header/body (auth.token_path)
    │         → self.session.headers["Authorization"] = f"Bearer {token}"
    │
    ├── auth.type == "dynamic_rest"?
    │     → _resolve_dynamic_rest()
    │         → POST to login endpoint with credentials
    │         → Extract token from response
    │         → Set Authorization header
    │
    ├── auth.type == "bearer"?
    │     → self.session.headers["Authorization"] = f"Bearer {auth.value}"
    │
    ├── auth.type == "api_key"?
    │     → self.session.headers[auth.header_name] = auth.value
    │
    └── No auth → plain HTTP requests
```

---

## 11. AUTHENTICATION ARCHITECTURE

The platform supports multiple authentication methods, all handled by `RestChatAdapter` and `BrowserAuthManager`.

### Auth Types Supported

#### 1. API Key
Config:
```json
{"auth": {"type": "api_key", "header_name": "X-API-Key", "value": "my-api-key"}}
```
What happens: Sets `X-API-Key: my-api-key` header on every request. Resolved at `__init__`.

#### 2. Bearer Token
Config:
```json
{"auth": {"type": "bearer", "value": "eyJhbGciOiJSUzI1..."}}
```
What happens: Sets `Authorization: Bearer {token}` header on every request. Resolved at `__init__`.

#### 3. Browser Token (Clerk/JWT)
Config:
```json
{
  "auth": {
    "type": "browser_token",
    "url": "https://app.example.com/chat",
    "intercept_pattern": "*/api/v1/admin/*",
    "token_path": "header:authorization",
    "header_name": "Authorization",
    "header_format": "Bearer {token}"
  },
  "storage_state": "auth-state-MyApp.json"
}
```
What happens:
1. At `__init__`, restores saved session (cookies + localStorage + sessionStorage)
2. Opens headless Playwright browser
3. Navigates to `url`
4. Sets up network interceptor matching `intercept_pattern`
5. Waits for a real API request to match
6. Extracts token from the request's Authorization header
7. Uses that live JWT for all subsequent evaluation requests

Why this is needed: Short-lived JWTs (like Clerk tokens) can't be hardcoded. They expire in minutes. By extracting them fresh from a real authenticated browser session each time, we always have a valid token.

**One-time setup required (per connection):**
- Click "Open Login / Authenticate" in the UI
- A browser opens — log in normally (enter OTP if required)
- Click "Save Authentication"
- `storage_state` JSON is saved to `auth-state-MyApp.json`
- Future evaluations reuse the saved cookies/refresh tokens to silently refresh JWTs without OTP

#### 4. Dynamic REST (Login API)
Config:
```json
{
  "auth": {
    "type": "dynamic_rest",
    "login_url": "https://api.example.com/auth/login",
    "credentials": {"username": "user", "password": "pass"},
    "token_path": "data.access_token"
  }
}
```
What happens: POSTs to login endpoint, extracts token from response JSON at `token_path`, uses it as Bearer token.

#### 5. Storage State (Browser sessions)
Config:
```json
{"storage_state": "auth-state-MyApp.json"}
```
What happens: Restores saved Playwright session state (cookies, localStorage, custom sessionStorage). Used by BrowserChatAdapter for full browser automation.

### Browser Auth Manager — Detailed Flow

**Initial Setup (one-time per connection):**
```
UI: "Open Login / Authenticate" button clicked
    ↓
API.startBrowserAuth({url})
    ↓ POST /connections/browser-auth/start
    ↓
BrowserAuthManager.start_browser_auth(url)
    ↓ _PlaywrightThread starts Playwright
    ↓ Opens chromium (headed mode)
    ↓ Navigates to url
    ↓ Returns session_id
    ↓
User sees browser, logs in manually (username, password, OTP)
    ↓
UI: "Save Authentication" button clicked
    ↓
API.saveBrowserAuth({session_id, authenticated_selector, expected_url})
    ↓ POST /connections/browser-auth/save
    ↓
BrowserAuthManager.save_browser_auth(...)
    ↓ Verifies login succeeded (checks selector/URL/cookie)
    ↓ browser_context.storage_state() → cookies + localStorage
    ↓ _append_session_storage() → reads window.sessionStorage, adds to JSON
    ↓ Saves to auth-state-{connection_name}.json
    ↓ Returns {storage_state_path}
```

**Reuse (every evaluation):**
```
RestChatAdapter.__init__(config)
    ↓
_resolve_browser_token()
    ↓ Read auth-state-{connection_name}.json
    ↓ new_context_with_extended_storage(...)
    ↓   → Injects add_init_script() to restore sessionStorage
    ↓   → Creates context with storage_state (cookies + localStorage)
    ↓ Navigate to auth.url
    ↓ Intercept network request matching intercept_pattern
    ↓ Extract Authorization header from intercepted request
    ↓ session.headers["Authorization"] = "Bearer {fresh_jwt}"
    ↓
All subsequent HTTP requests use this token
```

---

## 12. SOPHIA AI — CASE STUDY & DEBUGGING LOG

### What is Sophia AI?

Sophia is an AI-powered assistant for property management systems, built by a client. It's accessible at:
- Frontend URL: `https://dev.pms.jointribex.com/sophia`
- API endpoint: `https://tribe-gateway.archietech.co/owners/api/v1/admin/sophia/ask`

### Why Sophia Was Challenging

Sophia uses **Clerk authentication** — a modern SaaS authentication provider that:
1. Issues short-lived JWTs (expire within minutes)
2. Uses refresh tokens stored in both cookies and sessionStorage
3. Can't be bypassed with static API keys
4. Requires OTP on first login

This meant the standard `bearer` auth approach (hardcode a token) was impossible.

### Issues Found and How They Were Resolved

**Issue 1: Static token expires**
- Problem: Copy-pasting a JWT from the browser worked for 1-2 minutes, then all requests got 401 Unauthorized
- Root cause: Clerk JWTs have short TTL
- Fix: Implemented `browser_token` auth type — extract fresh JWT at the start of each evaluation

**Issue 2: sessionStorage not saved by Playwright**
- Problem: After saving storage_state and restoring it, the app redirected to the login page instead of staying authenticated
- Root cause: Clerk stores refresh tokens in `window.sessionStorage`, which Playwright's `storage_state()` does NOT save (by design)
- Fix: `_append_session_storage()` — custom JS to serialize sessionStorage into the JSON file. On restore, `add_init_script()` injects sessionStorage values before page scripts run.

**Issue 3: OTP required every time**
- Problem: Every evaluation required the user to enter an OTP
- Root cause: Auth state wasn't being saved and restored properly
- Fix: Once sessionStorage fix was in place, the saved refresh cookies let Clerk silently issue new JWTs without OTP

**Issue 4: token interception timing**
- Problem: The page made API calls immediately on load, before the interceptor was registered
- Root cause: Race condition between Playwright interceptor setup and first network request
- Fix: Used Playwright's `route()` async interceptor pattern, registered before `page.goto()`, so it captures even the first request

**Issue 5: REST request format**
- Problem: Sophia's API expected `question` not `message`, and needed static fields `scope` and `module_context`
- Fix: `request_mapping` in the adapter config handles field name remapping and static field injection

**Issue 6: Response field extraction**
- Problem: Sophia returns `{"answer": "..."}` not `{"reply": "..."}`
- Fix: `response_mapping.reply_field: "answer"` tells the adapter where to find the response text

### Working Sophia Configuration

Confirmed working from `scripts/smoke_test_sophia.py`:
```python
config = {
    "endpoint": "https://tribe-gateway.archietech.co/owners/api/v1/admin/sophia/ask",
    "method": "POST",
    "storage_state": "auth-state-Sophia_AI.json",
    "auth": {
        "type": "browser_token",
        "url": "https://dev.pms.jointribex.com/sophia",
        "intercept_pattern": "*/owners/api/v1/admin/*",
        "token_path": "header:authorization",
        "header_name": "Authorization",
        "header_format": "Bearer {token}"
    },
    "request_mapping": {
        "message_field": "question",
        "session_id_field": "conversation_id",
        "static_fields": {
            "scope": "portfolio",
            "module_context": "portfolio"
        }
    },
    "response_mapping": {
        "reply_field": "answer"
    }
}
```

### Why the Smoke Test Worked but the UI Failed (And How It Was Fixed)

- **Smoke test worked** because it directly called `ScenarioExecutor` with a hand-crafted config, bypassing the connection storage and UI parsing layers.
- **UI failed** because the browser_token config fields (`browser_login_url`, `intercept_pattern`, etc.) were in `options` dict but `RestChatAdapter` expected them inside the `auth` dict.
- **Fix:** `parser.py` now explicitly moves these fields from `options` to `auth` when `auth.type == "browser_token"`.

### How browser_login_url vs auth.url Work Together

- `browser_login_url` (in `options`): The URL that is opened in the headless browser to silently refresh the session. Required for `browser_token` connections.
- `auth.url`: The URL set in the `auth` dict by the parser (renamed from `browser_login_url`). Used by `_resolve_browser_token()`.
- These are the same value — just stored in different places before and after parsing.

### Why OTP is No Longer Needed Every Evaluation

1. First login: User opens browser via "Open Login / Authenticate", enters OTP, clicks "Save Authentication"
2. Saved state: `auth-state-Sophia_AI.json` contains the Clerk refresh cookies + sessionStorage tokens
3. Future evaluations: Playwright loads this state, navigates to the app, Clerk's SDK reads its refresh cookie, silently fetches a new JWT, the JWT is intercepted, evaluation proceeds
4. No OTP: OTP is only required on initial device login. Refresh tokens persist for weeks/months.

---

## 13. FRONTEND ARCHITECTURE

### Overview

The frontend is a vanilla JavaScript Single-Page Application (SPA). No React, no Vue, no build system. Just `index.html`, `app.js`, and `style.css`.

All frontend code lives in `frontend/static/app.js` (1300 lines).

### Pages

| Page | Trigger | What It Shows |
|---|---|---|
| Dashboard | `App.navigate("dashboard")` | Stats (total/pass/fail/connections), recent 10 evaluations |
| Connections | `App.navigate("connections")` | Table of all saved connections with Test/Evaluate/Edit/Delete buttons |
| Evaluations | `App.navigate("evaluations")` | Full table of all evaluation results this session |
| Scenarios | `App.navigate("scenarios")` | List of `.yaml` files in the `scenarios/` folder |
| Settings | `App.navigate("settings")` | API URL configuration, backend health test |
| Eval Details | `App.navigate("eval-details", result)` | Full report for a single evaluation |

### Modals

| Modal | ID | Purpose |
|---|---|---|
| Add/Edit Connection | `modal-add-connection` | Create or edit a connection profile |
| Run Evaluation | `modal-run-eval` | Select scenario and run evaluation |
| Paste Scenario | `modal-paste-scenario` | Paste YAML to create new scenario |

### Key JavaScript Objects

**`Config`** (lines 1-20 in app.js):
```javascript
Config = {
    apiBase: "http://localhost:8000"
}
```
Configurable via Settings page.

**`API`** (lines 22-54):
Thin HTTP wrapper. Every method returns a Promise that throws on error.
```javascript
API.health()
API.listConnections()
API.createConnection(payload)
API.patchConnection(id, data)
API.deleteConnection(id)
API.testConnection(id)
API.evaluate(connId, scenPath)
API.startBrowserAuth(data)
API.saveBrowserAuth(data)
API.listScenarios()
API.validateScenario(data)
API.saveScenario(data)
API.getConnection(id)
```

**`State`** (lines 56-67):
```javascript
State = {
    connections: [],          // All loaded connections
    evaluations: [],          // All evaluations run this session
    scenarios: [],            // Available scenarios
    currentEval: null,        // Currently viewed evaluation
    pendingConnId: null,      // Connection selected for evaluation
    pendingConnData: null,    // Full connection object for pending eval
    editingConnId: null,      // Connection being edited
    interactiveAuthSession: null, // Active browser auth session ID
    backendOnline: false      // Backend health status
}
```

### Connection Form Fields

The Add Connection modal captures:
- **Name** → `conn-name`
- **Type** (chatbot/voice) → `conn-type`
- **Method** (rest/websocket/browser/livekit/local/fake) → `conn-method`
- **URL** → `conn-url`
- **Auth Type** → `conn-auth-type`
- **Auth Value** → `conn-auth-value`
- **Options** (JSON) → `conn-options`

For browser connections:
- Input selector, submit selector, response selector

For browser_token auth:
- Browser Login URL, intercept pattern, token path, header name, header format

For browser auth session:
- Authentication selector, expected URL after login, required cookie name

### Evaluation Flow (Frontend)

```javascript
App.openEvalModal(connId)
    ↓ Load connection details
    ↓ Load scenarios, filter by agent type (voice/chatbot)
    ↓ Display in modal

App.runEvaluation()
    ↓ Validate scenario selected
    ↓ App.closeModal("modal-run-eval")
    ↓ App.navigate("eval-details")
    ↓ App._showEvalRunning() — spinner
    ↓ result = await API.evaluate(connId, scenPath)   // ~30-120 seconds
    ↓ State.evaluations.push(result)
    ↓ State.currentEval = result
    ↓ App.navigate("eval-details", result)
    ↓ toast("✓ Evaluation passed! Score: 0.82", "success")
```

### Report Rendering

`App.renderEvalDetails(ev)` builds HTML dynamically:

1. **Back button** → goes to Evaluations list
2. **Agent header** → name, type badge, adapter, scenario, timestamp, session ID
3. **Summary cards** → Overall Score, Status (PASS/FAIL/ERROR), Agent Type, Metric count
4. **Error banner** → Only shown if `ev.success === false`
5. **Conversation section** → Each turn rendered as `turn-user` or `turn-agent` bubble with speaker label
6. **Evaluation Metrics section** → For each `MetricResult`: name, score bar, pass/fail badge, reason text
7. **Voice Metrics section** → Only shown if `ev.voice_metrics` exists; same format as eval metrics

### Browser Auth Recovery

If browser token auth has expired, the frontend detects it via `App._isBrowserAuthExpiredError(message)` which checks for keywords:
- `"failed to extract browser token"`
- `"browser token auth requires"`
- `"storage_state"` + `"not found"/"expired"/"invalid"`
- `"authentication"` + `"expired"/"revoked"/"login"`

Recovery message displayed to user:
> "Saved browser authentication is missing, expired, or revoked. Open this connection, run Open Login / Authenticate again, complete OTP, then Save Authentication to overwrite the auth-state file."

---

## 14. REPORT GENERATION

### How Reports Are Generated

There is no separate "report generation" module. Reports are generated dynamically by the frontend's `App.renderEvalDetails()` function from the JSON data returned by the backend.

### Report Data Structure (stored in SQLite and returned as JSON)

```json
{
  "run_id": "uuid-...",
  "scenario_id": "refund_request_v1",
  "agent_id": "connection-uuid",
  "agent_type": "chatbot",
  "adapter": "rest",
  "success": true,
  "passed": true,
  "overall_score": 0.82,
  "pass_threshold": 0.7,
  "session_id": "uuid-...",
  "conversation": [
    {"speaker": "user", "message": "Hi, I need help with my order"},
    {"speaker": "agent", "message": "Hello! I'd be happy to help..."}
  ],
  "metrics": [
    {"name": "Goal Completion", "score": 0.90, "reason": "Agent successfully...", "passed": true},
    {"name": "Persona and Tone Adherence", "score": 0.85, "reason": "Agent maintained...", "passed": true},
    {"name": "Conversational Quality", "score": 0.70, "reason": "Context tracking...", "passed": true}
  ],
  "voice_metrics": null,
  "error": null,
  "created_at": "2024-01-15T10:30:00Z"
}
```

### Dependencies (requirements.txt)

```
fastapi==0.115.0           # Web framework
uvicorn[standard]==0.30.6  # ASGI server
pydantic==2.9.2            # Data validation
pydantic-settings==2.5.2   # Settings management
deepeval==2.0.9            # LLM evaluation framework
google-generativeai==0.8.3 # Gemini API
requests==2.32.3           # HTTP client
pyyaml==6.0.2              # YAML parsing
python-dotenv==1.0.1       # .env loading
groq                       # Groq API (no pinned version)
sounddevice                # Audio device access (voice)
numpy                      # Audio processing (voice)
faster-whisper             # STT (voice)
piper-tts                  # TTS (voice)
```

**Not in requirements.txt but used:**
- `playwright` (for browser auth) — needs `pip install playwright && playwright install chromium`
- `livekit` SDK (for LiveKit voice adapter)

### Environment Variables Reference

File: `.env` (copy from `.env.example`)

```
GEMINI_API_KEY=...          # Required for judge fallback
GEMINI_MODEL=gemini-2.0-flash

GROQ_API_KEY=...            # Required for simulator AND primary judge
GROQ_MODEL=llama-3.1-8b-instant

OLLAMA_BASE_URL=...         # Present but not used by current code
OLLAMA_MODEL=...            # Present but not used by current code

DB_PATH=./eval_results.db   # SQLite file location

MAX_TURNS_PER_RUN=12        # Upper bound for scenario max_turns
MIN_TURNS_PER_RUN=2         # Lower bound
```

---

## 15. DATABASE ARCHITECTURE

### Database

- **Type:** SQLite
- **File:** `eval_results.db` (configurable via `DB_PATH` env var)
- **Two tables:** `test_runs` and `agent_connections`
- **Created automatically** on first use

### Table: `test_runs`

Stores evaluation results.

| Column | Type | Description |
|---|---|---|
| `run_id` | TEXT PRIMARY KEY | UUID for this evaluation run |
| `scenario_id` | TEXT | Scenario identifier from YAML |
| `agent_json` | TEXT | JSON: AgentConfig (channel, adapter, config) |
| `transcript_json` | TEXT | JSON: list of `{role, content, turn_index, ...}` messages |
| `metrics_json` | TEXT | JSON: list of `{name, score, reason, passed}` |
| `voice_metrics_json` | TEXT | JSON: same as metrics but voice-specific (nullable) |
| `overall_score` | REAL | Average score (0.0-1.0) |
| `passed` | INTEGER | 1 if passed, 0 if failed |
| `created_at` | TEXT | ISO 8601 timestamp |

**Additional context available at runtime (not in DB):**
- `agent_id` — connection ID (from API layer, not stored in test_runs)
- `agent_type` — chatbot or voice (from API layer)
- `adapter` — adapter name (from API layer)

### Table: `agent_connections`

Stores connection profiles.

| Column | Type | Description |
|---|---|---|
| `id` | TEXT PRIMARY KEY | UUID for this connection |
| `name` | TEXT | Human-readable label |
| `type` | TEXT | `"chatbot"` or `"voice"` |
| `adapter` | TEXT | Adapter name: `rest`, `browser`, `livekit`, etc. |
| `config_json` | TEXT | JSON: full adapter config dict (includes auth, URLs, mappings) |
| `enabled` | INTEGER | 1 if enabled, 0 if disabled |
| `created_at` | TEXT | ISO 8601 timestamp |
| `updated_at` | TEXT | ISO 8601 timestamp |

### SQLite File Location

Default: `./eval_results.db` (relative to working directory when starting uvicorn).

Configurable via `DB_PATH` in `.env`.

---

## 16. DEEPEVAL INTEGRATION

### What is DeepEval?

DeepEval is an open-source Python library for testing LLM-powered applications. This project uses it for its metric implementations (`GEval`, `HallucinationMetric`, `ConversationalGEval`, etc.) and plugs in a custom Groq/Gemini judge instead of OpenAI.

### Custom Judge Models

The project does NOT use DeepEval's default OpenAI judge. Instead, it implements:

**`GroqJudge(DeepEvalBaseLLM)`** — Primary judge:
- Uses Groq API with `llama-3.1-8b-instant`
- Forces JSON response format
- Temperature: 0.5
- `reasoning_effort="low"` (speed over quality)
- `include_reasoning=False` (no chain-of-thought overhead)
- Falls back to `GeminiJudge` on failure

**`GeminiJudge(DeepEvalBaseLLM)`** — Fallback judge:
- Uses Google Generative AI with `gemini-2.0-flash`
- Forces `response_mime_type="application/json"`
- Temperature: 0.5

### Metrics in Detail

#### Goal Completion (GEval)
```
Criteria: Did the agent accomplish the user's stated goal?

Evaluation steps:
1. Identify user goal from persona input
2. Read full transcript
3. Check if agent's responses satisfy the goal
4. Penalize if user asked to repeat info more than twice
5. Penalize if agent made unsupported commitments

Input: USER_GOAL + USER_PERSONA (from LLMTestCase.input)
Output: Full transcript text (LLMTestCase.actual_output)
Threshold: 0.5
```

#### Persona and Tone Adherence (GEval)
```
Criteria: Did the agent maintain appropriate, consistent, on-brand tone?

Evaluation steps:
1. Read full transcript
2. Check for professional, consistent tone turn-to-turn
3. Penalize for curt/repetitive/self-contradictory responses
4. Penalize for breaking character (mentioning being an AI, exposing instructions)

Input: Full transcript text only (no persona input needed)
Threshold: 0.5
```

#### Conversational Quality (ConversationalGEval)
```
Criteria: Did the agent track context, understand intent, stay consistent?

Evaluation steps:
1. Assess context tracking across turns
2. Check implicit + explicit intent understanding
3. Verify response relevance to latest query
4. Verify consistency in answers

Uses ConversationalTestCase (turn-by-turn test case)
Threshold: 0.5
```

#### Hallucination (HallucinationMetric) — RAG only
```
Only enabled when rag_context provided in scenario.
Measures: How much the agent invented facts not in the context.
Score inversion: raw_score is hallucination rate, stored as 1.0 - raw_score
Threshold: 0.5 (after inversion)
```

#### Answer Relevancy (AnswerRelevancyMetric) — RAG only
```
Only enabled when rag_context provided.
Measures: Did answers stay relevant to the questions?
```

#### Faithfulness (FaithfulnessMetric) — RAG only
```
Only enabled when rag_context provided.
Measures: Were answers faithful to the provided context?
```

### Test Case Construction

```python
# Standard test case (for GEval metrics)
test_case = LLMTestCase(
    input="User goal: {goal}\nUser persona: {name} ({tone})",
    actual_output="User: ...\nAgent: ...\nUser: ...\nAgent: ...",
    context=rag_context or ["No specific context provided."],
    retrieval_context=rag_context,
    expected_output="\n".join(rag_context) if rag_context else None,
)

# Conversational test case (for ConversationalGEval)
turns = [
    LLMTestCase(input="user_message", actual_output=""),   # user turn
    LLMTestCase(input="", actual_output="agent_message"),  # agent turn
    ...
]
conversational_test_case = ConversationalTestCase(turns=turns)
```

### How Overall Score Is Computed

```
overall_score = mean(metric.score for metric in results)
passed = overall_score >= scenario.pass_threshold  (default: 0.7)
```

Example:
```
Goal Completion:       0.90  ✓
Tone Adherence:        0.85  ✓
Conversational:        0.70  ✓
Overall:               0.82  → PASS (threshold: 0.7)
```

---

## 17. IMPLEMENTED VS. PLANNED FEATURES

### Currently Implemented

| Feature | Status | Evidence |
|---|---|---|
| FastAPI backend | ✅ Working | `app/main.py` |
| Web UI (full SPA) | ✅ Working | `frontend/static/app.js` |
| Connection CRUD | ✅ Working | `app/connections/api.py`, `storage.py` |
| REST chatbot adapter | ✅ Working | `app/adapters/chat/rest.py` |
| Multi-step REST protocol | ✅ Working | `rest.py` `is_multi_step` flag |
| Browser chatbot adapter | ✅ Working | `app/adapters/chat/browser.py` |
| Fake chatbot adapter | ✅ Working | `app/adapters/chat/fake.py` |
| Browser auth (Playwright) | ✅ Working | `app/connections/browser_auth.py` |
| SessionStorage persistence | ✅ Working | `_append_session_storage()` custom fix |
| JWT token interception | ✅ Working | `_resolve_browser_token()` |
| Groq-powered simulator | ✅ Working | `app/simulator.py` |
| Groq judge (primary) | ✅ Working | `app/evaluator.py` `GroqJudge` |
| Gemini judge (fallback) | ✅ Working | `app/evaluator.py` `GeminiJudge` |
| Goal Completion metric | ✅ Working | DeepEval GEval |
| Tone Adherence metric | ✅ Working | DeepEval GEval |
| Conversational Quality metric | ✅ Working | DeepEval ConversationalGEval |
| Hallucination metric (RAG) | ✅ Working | DeepEval HallucinationMetric |
| Answer Relevancy (RAG) | ✅ Working | DeepEval AnswerRelevancyMetric |
| Faithfulness (RAG) | ✅ Working | DeepEval FaithfulnessMetric |
| SQLite storage (test_runs) | ✅ Working | `app/storage.py` |
| SQLite storage (connections) | ✅ Working | `app/connections/storage.py` |
| LiveKit voice adapter | ✅ Implemented | `app/adapters/voice/livekit.py` |
| Local voice adapter (Piper+Whisper) | ✅ Implemented | `app/adapters/voice/local.py` |
| Voice metrics (6 metrics) | ✅ Implemented | `app/voice/metrics.py` |
| Voice persona engine | ✅ Implemented | `app/voice/persona.py` |
| Scenario YAML system | ✅ Working | `scenarios/*.yaml` |
| Scenario paste UI | ✅ Working | `app.js` `openPasteScenarioModal()` |
| Connection test (live probe) | ✅ Working | `manager.test_connection()` |
| [END_CONVERSATION] signal | ✅ Working | `executor.py` loop check |
| Attachment handling (simulator) | ✅ Implemented | `simulator.py` regex extraction |

### Not Implemented / Stubs

| Feature | Status | Evidence |
|---|---|---|
| WebSocket adapter (functional) | ⚠️ Stub | `websocket.py` returns hardcoded string |
| Interactive framework (runtime) | ⚠️ Models only | `app/interactive/` not wired into execution |
| Ollama simulator | ⚠️ Config exists, not used | `config.py` has ollama keys, `simulator.py` uses Groq |
| SSE adapter | ❌ Not registered | Registry docstring says "not yet" |
| SIP/Phone adapters | ❌ Not registered | Registry docstring says "not yet" |
| PDF/HTML report export | ❌ Not implemented | Not confirmed from codebase |
| Run history from DB on page load | ⚠️ Partial | State.evaluations starts empty each session; only loads from DB via legacy /test-runs |
| Multi-user/auth | ❌ Not implemented | No user authentication in the platform itself |
| Scheduled evaluations | ❌ Not implemented | Not confirmed from codebase |
| Webhook notifications | ❌ Not implemented | Not confirmed from codebase |

---

## 18. FUTURE ARCHITECTURE (INTERACTIVE FRAMEWORK)

The `app/interactive/` package is a foundation for evaluating **interactive AI** — chatbots that present buttons, dropdowns, quick replies, date pickers, upload requests, etc.

### Current State (Phase 1)

All classes exist as data models and validators. None are connected to the execution pipeline.

### What Is Built

**`models.py`** — Full data type vocabulary:
- 14 `InteractiveElementType` values (button, quick_reply, card, form, upload_request, date_picker, etc.)
- 12 `ActionType` values (send_text, click_button, select_dropdown, upload_file, dtmf, wait, etc.)
- `UserAction` — proposed action to take
- `NormalizedAgentResponse` — parsed agent response with interactive elements
- `ActionValidationResult` — validation outcome

**`capability_registry.py`** — Declarative adapter capabilities:
```python
# chatbot adapters support: send_text, click_option, click_button
# voice adapters support: send_text, wait, dtmf
```

**`action_validator.py`** — Shape + capability validation:
```python
validator.validate(action, adapter_name="rest")
# → ActionValidationResult(valid=True, normalized_action=action)
# → ActionValidationResult(valid=False, reason="Adapter 'rest' does not support 'upload_file'")
```

**`response_understanding.py`** — Response parsing:
```python
ResponseUnderstanding().normalize(text="Please choose:\n- Option A\n- Option B")
# → NormalizedAgentResponse(
#       text="Please choose:\n- Option A\n- Option B",
#       interactive=[
#           InteractiveElement(type=quick_reply, label="Option A"),
#           InteractiveElement(type=quick_reply, label="Option B"),
#       ]
#   )
```

**`conversation_state.py`** — State for future planner:
```python
ConversationState(
    current_goal="Get a refund",
    available_actions=["Option A", "Option B"],
    conversation_memory=["Turn 1: ...", "Turn 2: ..."],
    ...
)
```

### Planned Future Phases

Phase 2 (not implemented): Wire `ResponseUnderstanding` into the send/receive loop so interactive elements are parsed from each agent response.

Phase 3 (not implemented): Connect `ConversationState` to a planner that selects `UserAction` based on available interactive elements.

Phase 4 (not implemented): Adapter-native metadata — adapters return rich metadata alongside text, so element detection isn't based on heuristics.

---

## 19. END-TO-END DATA FLOW DIAGRAMS

### Chatbot Evaluation Data Flow

```
SCENARIO YAML
    ↓ yaml.safe_load()
TestScenario (Pydantic)
    ↓ executor.execute(connection, scenario)
    │
    ├── [TURN LOOP]
    │     Persona + Transcript
    │         ↓ simulator.generate_next_user_turn()
    │     Groq API → raw text
    │         ↓ strip [ATTACHMENT:...] tags
    │     {message, attachments}
    │         ↓ adapter.send_message()
    │     HTTP POST → Chatbot API
    │         ↓ HTTP response
    │     agent_reply (string)
    │         ↓ build ConversationMessage
    │     transcript.append(user_turn)
    │     transcript.append(agent_turn)
    │
    ├── ExecutionResult(transcript=list[ConversationMessage])
    │
    └── EvaluationService.evaluate()
            ↓ _transcript_to_text()
        "User: ...\nAgent: ...\nUser: ..."
            ↓ LLMTestCase(input=goal, actual_output=transcript_text)
            ↓ metric.measure(test_case)   [x3 or x6]
        Groq API → JSON score + reason
            ↓ MetricResult(name, score, reason, passed)
            ↓ mean(scores) → overall_score
            ↓ overall_score >= threshold → passed
            ↓ storage.save_run()
        SQLite INSERT
            ↓ return TestRunResult JSON
        HTTP Response → Frontend
```

### Browser Token Auth Data Flow

```
auth-state-Sophia_AI.json
    ↓ read JSON
{cookies: [...], origins: [...], _evalforge_sessionStorage: {...}}
    ↓ browser_context = playwright.chromium.new_context(storage_state=...)
    ↓ add_init_script()  ← injects sessionStorage restore script
    ↓ page = context.new_page()
    ↓ route("*/owners/api/v1/admin/*", intercept_handler)
    ↓ page.goto("https://dev.pms.jointribex.com/sophia")
Page loads → Clerk SDK reads refresh cookie → calls /tokens
    ↓ intercept_handler fires
Request headers: {Authorization: "Bearer eyJhbGci..."}
    ↓ extract "eyJhbGci..." token
    ↓ close browser
session.headers["Authorization"] = "Bearer eyJhbGci..."
    ↓ all future requests use this header
POST https://tribe-gateway.archietech.co/owners/api/v1/admin/sophia/ask
    Headers: {Authorization: Bearer eyJhbGci...}
    Body: {question: "Hello", conversation_id: "uuid", scope: "portfolio", ...}
```

### Voice Evaluation Data Flow

```
VoiceConversation (empty)
    ↓ adapter.start_session()
VoiceSession(status=active, started_at=now)
    ↓ [TURN LOOP]
        ↓ generate_next_user_turn(persona, transcript)  [Groq API]
    user_text = "I need to report a water leak"
        ↓ PiperTTS.synthesize(user_text)
    user_wav (bytes, 16-bit mono PCM, WAV header)
        ↓ adapter.send_audio(user_wav)
        ↓ FasterWhisperSTT.transcribe(user_wav)  [local model]
    user_transcript_text
    VoiceTurn(speaker=user, text=user_transcript_text, audio_path=...)
        ↓ adapter.receive_audio()
    agent_wav (bytes, from LiveKit or HTTP endpoint)
        ↓ FasterWhisperSTT.transcribe(agent_wav)
    agent_transcript_text
    VoiceTurn(speaker=agent, text=agent_transcript_text, latency_ms=..., audio_path=...)
    ↓ adapter.end_session()
VoiceConversation(session, turns=[...], events=[...])
    ↓ run_voice_metrics(vc, config)
[Response Latency, Turn Taking, Interruptions, Silence, Audio Evidence, Session Completion]
    ↓ voice_converter.to_normalized_conversation(vc)
NormalizedConversation → evaluate_transcript() → [LLM metrics]
    ↓ combine all metrics
TestRunResult → storage.save_run() → HTTP response
```

---

## 20. CODE DEPENDENCY GRAPH

```
app/main.py
    ├── app/connections/api.py
    │       ├── app/executor.py
    │       │       ├── app/simulator.py
    │       │       │       ├── app/config.py
    │       │       │       └── app/schemas.py
    │       │       ├── app/connections/manager.py
    │       │       │       └── app/connections/registry.py
    │       │       │               ├── app/adapters/chat/rest.py
    │       │       │               │       ├── app/connections/browser_auth.py
    │       │       │               │       └── app/models/conversation.py
    │       │       │               ├── app/adapters/chat/browser.py
    │       │       │               ├── app/adapters/chat/websocket.py
    │       │       │               ├── app/adapters/chat/fake.py
    │       │       │               ├── app/adapters/voice/livekit.py
    │       │       │               ├── app/adapters/voice/local.py
    │       │       │               └── app/adapters/voice/fake.py
    │       │       └── app/voice/persona.py
    │       │               ├── app/simulator.py
    │       │               └── app/voice/audio.py
    │       ├── app/evaluation_service.py
    │       │       ├── app/evaluator.py
    │       │       │       ├── app/config.py
    │       │       │       └── app/schemas.py
    │       │       ├── app/voice/metrics.py
    │       │       │       ├── app/schemas.py
    │       │       │       └── app/models/voice.py
    │       │       └── app/voice/converter.py
    │       ├── app/connections/storage.py
    │       └── app/connections/parser.py
    │               ├── app/connections/input.py
    │               ├── app/connections/manager.py
    │               └── app/models/connection.py
    ├── app/orchestrator.py (legacy)
    │       ├── app/adapters/factory.py (legacy)
    │       ├── app/simulator.py
    │       ├── app/evaluator.py
    │       └── app/storage.py
    └── app/storage.py
```

---

## 21. DEBUGGING GUIDE

### Common Issues and Solutions

#### Backend won't start

**Symptom:** `uvicorn app.main:app` fails with ImportError

**Check:**
1. Is `.env` file present? Check: `copy .env.example .env`
2. Are dependencies installed? Run: `pip install -r requirements.txt`
3. Is Playwright installed? Run: `pip install playwright && playwright install chromium`

---

#### "Backend offline" shown in UI

**Symptom:** Red dot in top-right corner of UI

**Check:**
1. Is the backend running? Try: `curl http://localhost:8000/health`
2. Is the API URL in Settings correct? Check Settings page → API URL field
3. CORS issue? Check browser console for CORS errors.

---

#### Evaluation fails immediately with "Groq" error

**Symptom:** Error message contains "Groq" or "llama-3.1"

**Check:**
1. Is `GROQ_API_KEY` set in `.env`?
2. Is the Groq API key valid? Check at console.groq.com
3. Network connectivity? Can you reach `api.groq.com`?

---

#### "Failed to extract browser token" error

**Symptom:** Evaluation fails with this message for browser_token connections

**What to do:**
1. Open the connection in the UI (Edit button)
2. Click "Open Login / Authenticate"
3. A browser opens — log in to the target website
4. Complete any OTP/2FA if prompted
5. Click "Save Authentication"
6. Try evaluation again

**Why it happens:** The saved auth state expired, or the target site revoked the session.

---

#### Browser redirects to login page during evaluation

**Symptom:** BrowserChatAdapter logs show "After goto - Final URL: ...login..."

**What to do:**
1. Same as above — re-authenticate via UI
2. Check that `authenticated_selector` is correct — the one you specified when saving auth

---

#### Evaluation completes but score is 0

**Symptom:** All metrics show score 0.0

**Possible causes:**
1. Empty transcript — adapter failed to communicate
2. Judge model returned invalid JSON — check logs for `[EVAL METRIC FAILED]`
3. `rag_context` provided but context is empty — hallucination metric gets confused

---

#### Playwright errors on Windows

**Symptom:** "There is no current event loop in thread 'MainThread'"

**What happened:** Playwright requires ProactorEventLoop on Windows. The code uses `_PlaywrightThread` to handle this.

**If you see this:** Check if Playwright is being called outside of the designated thread. All Playwright calls must go through `BrowserAuthManager.get_instance()` or `_BrowserThread.dispatch()`.

---

#### Voice evaluation hangs

**Symptom:** Evaluation starts but never completes

**Check:**
1. Is LiveKit server reachable? Check `server_url` in connection config
2. Is `max_session_duration_seconds` too long? Default is 900 (15 minutes)
3. Check logs for `[VOICE DEBUG]` messages — identifies which step hung

---

### Key Log Patterns to Watch

```
[STAGE: Simulated User Generation] turn_index=0 elapsed=1.234s
[STAGE: Fake Agent Request] elapsed=0.456s
[EVALUATION START]
[EVAL METRIC START] Goal Completion
[EVAL METRIC END] Goal Completion duration=3.21s
[EVALUATION END] total_duration=11.5s

[STAGE: Simulated User Generation FAILED] exception=GroqError: ...
[EVAL METRIC FAILED] Goal Completion error=RuntimeError: Judge model returned invalid JSON
[VOICE DEBUG 5] VoicePersonaEngine started
[VOICE DEBUG 6] LiveKit session started
```

---

## 22. NEW ENGINEER ONBOARDING

### Day 1: Setup

**1. Install Python 3.11+**

**2. Clone/navigate to the project:**
```
d:\bestQ\evalution-ai-agent\
```

**3. Create .env file:**
```
copy .env.example .env
```
Edit `.env` and fill in your actual API keys.

**4. Install dependencies:**
```
pip install -r requirements.txt
pip install playwright
playwright install chromium
```

**5. Start the backend:**
```
cd d:\bestQ\evalution-ai-agent
uvicorn app.main:app --reload --port 8000
```

**6. Open the frontend:**
Open browser: `http://localhost:8000`

**7. Run a test evaluation:**
- Go to Connections → Add Connection
- Name: "Test Bot", Type: chatbot, Method: REST API
- URL: `http://localhost:8000/mock-chat` (the built-in mock)
- Save Connection
- Click Evaluate → Select "refund_request_v1" → Run Evaluation
- Watch the evaluation complete in ~30-60 seconds

---

### Key Files to Read First (in order)

1. `app/schemas.py` — Understand the data structures (20 min)
2. `app/config.py` — Understand settings (5 min)
3. `app/connections/api.py` → `evaluate_connection()` — The main production flow (30 min)
4. `app/executor.py` — How conversations are run (20 min)
5. `app/simulator.py` — How the simulated user works (10 min)
6. `app/evaluator.py` — How scoring works (30 min)
7. `app/adapters/chat/rest.py` — The most complex adapter (45 min)
8. `app/connections/browser_auth.py` — Browser auth internals (30 min)

---

### Key Concepts to Understand

| Concept | Where to Look | Why Important |
|---|---|---|
| Adapter pattern | `app/adapters/chat/base.py` | Every chatbot integration follows this |
| [END_CONVERSATION] | `app/executor.py` loop, `app/simulator.py` | Conversation termination |
| Browser token flow | `app/adapters/chat/rest.py` `_resolve_browser_token()` | How Sophia-type auth works |
| SessionStorage gap | `app/connections/browser_auth.py` `_append_session_storage()` | Critical Playwright limitation fix |
| Two execution paths | `app/main.py` vs `app/connections/api.py` | Legacy vs production |
| DeepEval test case | `app/evaluator.py` `evaluate_transcript()` | How scoring is triggered |
| Pass threshold | `app/schemas.py` `TestScenario.pass_threshold` | What "PASS" means |

---

### How to Add a New Chatbot Integration

1. **Create a connection** in the UI with the chatbot's URL and auth type
2. **Test the connection** using the Test button
3. **Create a YAML scenario** file in `scenarios/` folder:
   ```yaml
   scenario_id: my_new_test_v1
   agent:
     channel: chatbot
     adapter: rest
   persona:
     name: "TestUser"
     goal: "Test the chatbot's ability to answer FAQ questions"
     tone: "neutral and professional"
   max_turns: 5
   pass_threshold: 0.7
   ```
4. **Run evaluation** by selecting the connection and scenario

---

### How to Add a New Adapter Type

1. Create a new file in `app/adapters/chat/` or `app/adapters/voice/`
2. Extend `ChatAdapter` or `VoiceAdapter` base class
3. Implement required abstract methods
4. Register in `app/connections/registry.py`:
   ```python
   registry.register(
       "chatbot", "myprotocol",
       lambda cfg: _import_and_create("app.adapters.chat.myprotocol", "MyProtocolAdapter", cfg),
   )
   ```
5. Add to `app/adapters/factory.py` for legacy support (optional)

---

## 23. MANAGER EXPLANATION

### 1-Minute Version

This is a quality-testing tool for AI chatbots. You connect any AI agent to it, pick a test scenario (e.g., "customer asking for a refund"), and the platform automatically:
- Simulates a realistic customer conversation
- Sends real messages to the AI being tested
- Grades the AI's performance using a separate AI judge

The result is a **pass/fail score** with detailed reasons — telling you exactly where the AI succeeded or failed. It saves the team from manually testing chatbots and gives repeatable, objective scores.

---

### 5-Minute Version

**The Problem:** AI chatbots are hard to test. You can't just check "did it say the right string" — you need to judge conversation quality, tone, goal completion, and consistency. Manual testing is slow and subjective.

**The Solution:** This platform automates AI testing using a 3-layer approach:
1. **Simulated User** — An LLM (Groq/llama-3.1-8b) plays the role of a realistic customer with a persona, goal, and optional adversarial behavior
2. **Adapter Layer** — Connects to any chatbot (REST API, browser UI, voice agents) regardless of how it's built
3. **LLM Judge** — A separate AI (Groq with Gemini fallback) scores the conversation on 3-6 dimensions: goal completion, tone, conversational quality, and optionally hallucination/faithfulness

**Key capabilities:**
- Works with complex authenticated agents (browser login, OTP, Clerk JWT)
- Handles voice agents via LiveKit WebRTC or local audio processing
- Full web UI — no coding required to run evaluations
- Results stored in SQLite, displayed as reports

**Current state:** Chatbot evaluation is fully working. Voice evaluation is implemented. Browser authentication (including Sophia AI with Clerk) is solved.

---

### 10-Minute Version

**Architecture (3 tiers):**

*Tier 1 — Frontend:* Single-page app in vanilla JavaScript. Users manage connections (saved chatbot configs), run evaluations, view reports. No build system — just HTML + JS + CSS.

*Tier 2 — Backend:* FastAPI (Python) with two parallel execution paths:
- Legacy path (`/test-runs`) for direct API testing
- Production path (`/connections/{id}/evaluate`) — the main flow used by the UI

*Tier 3 — Integrations:* Groq API (simulator + judge), Google Gemini (judge fallback), Playwright (browser automation), LiveKit (voice), SQLite (storage)

**How an evaluation runs (simplified):**
1. User selects a connection (saved chatbot config) and a scenario (YAML test definition)
2. Backend loads both, creates the appropriate adapter (REST/Browser/LiveKit)
3. Simulator generates a user message → sends to chatbot → captures reply → repeat for N turns
4. Transcript is sent to the LLM judge → scores returned
5. Overall score computed (average of all metric scores) → compared to threshold → PASS or FAIL
6. Saved to SQLite, returned to frontend as a structured report

**Browser authentication (the hardest part):**
For agents like Sophia AI that use Clerk (short-lived JWTs + OTP), we:
- Run a one-time setup where the user logs in manually through a Playwright browser
- Capture and save the entire session state (including sessionStorage, which Playwright normally misses)
- At evaluation time, reload the session silently, intercept the fresh JWT from network traffic, use it

**Scale and limitations:**
- All data is per-session in memory + SQLite (single server, no multi-user)
- One evaluation runs synchronously (~30-120 seconds)
- No scheduled evaluations, no webhooks, no user authentication on the platform itself
- Voice testing works but requires manual setup (LiveKit server, Piper model files)

**What makes this different from standard test frameworks:**
Most frameworks test specific outputs. This tests **behavior quality** — something only an LLM judge can assess. It's designed for when you need to ask "was the chatbot actually helpful?" rather than "did it return the expected string?"

---

*End of PROJECT_ARCHITECTURE.md*
*Generated: 2026-10-01 | Based exclusively on codebase at d:\bestQ\evalution-ai-agent*
*All claims are traceable to actual source files. Nothing is assumed or guessed.*
