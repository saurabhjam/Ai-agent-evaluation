# Project Brain

This file acts as the persistent memory and single source of truth for the EvalForge project architecture, implementation, and important changes.

## 1. Project Overview

EvalForge (Voice Agent & Chatbot Evaluation) is a minimal, runnable proof-of-concept platform for testing AI voice agents and chatbots. It allows for testing scenarios where a simulated user interacts with a chatbot or voice agent. The conversation is then judged using DeepEval metrics (via a Gemini-based judge). Everything is validated with Pydantic.

**Key Use Cases:**
- Run simulated conversations against chatbot endpoints via REST adapters.
- Run voice simulations using Local or LiveKit adapters.
- Evaluate transcripts using GEval metrics (Goal Completion, Tone Adherence, Hallucination) via Gemini.
- Authenticate and proxy requests to third-party endpoints (like Sophia via Playwright).

## 2. Architecture

**High-Level Architecture:**
The platform is built on FastAPI. It runs simulations asynchronously using `app.orchestrator` and records test runs in SQLite.

**Major Components:**
- **Simulator:** Uses Ollama (e.g. `llama3.1:8b`) to simulate user personas and generate responses.
- **Adapters:** Connect to external agent endpoints (REST Chat, Browser Auth, Local Voice, LiveKit Voice).
- **Evaluator:** Evaluates conversations using DeepEval/Gemini once the conversation concludes.
- **Orchestrator:** Handles the main scenario loop, sending messages back and forth.
- **Connections/Auth Manager:** A thread-safe Playwright manager for UI-driven browser authentication flows.

## 3. Project Structure

- `app/` - Main application package
  - `main.py` - FastAPI application entry point.
  - `config.py` - Configuration loading via `.env`.
  - `schemas.py` - Pydantic models for validation.
  - `orchestrator.py` - Manages the back-and-forth execution of scenarios.
  - `simulator.py` - The Ollama simulated user.
  - `evaluator.py` - DeepEval integrations and Gemini configuration.
  - `storage.py` - SQLite operations for saving runs.
  - `adapters/` - Adapters for various interfaces (e.g., chat/REST).
  - `connections/` - Browser authentication logic, APIs for connections, registries, and connection storage.
  - `voice/` - Voice specific adapters (Local, LiveKit) and utilities for STT/TTS.
  - `models/` - SQLAlchemy models and DB logic.
- `frontend/` - Simple HTML/JS single-page application.
- `scenarios/` - YAML configuration for tests.
- `scripts/` - Standalone utility scripts like `smoke_test_sophia.py` and `manual_login.py`.
- `tests/` - Pytest coverage for all modules.
- `models/` - Assets or binaries for voice or other models (e.g., ONNX TTS).
- `app/interactive/` - Phase 1 foundation for the future User Action Engine. It currently contains dependency-free, vendor-neutral models and utilities only; it is not integrated into runtime execution.
- `app/calling/` - AI Calling Agent Evaluation foundation and UI integration. It contains vendor-neutral call/session/event/artifact/transcript models, an abstract provider adapter contract, a normalizer to produce the existing `NormalizedConversation` shape, an in-memory lifecycle simulator, plugin-style provider registry/factory/resolver infrastructure, a universal ConversationEvidence bridge, an explicitly instantiated calling runtime execution pipeline, a bridge into the existing evaluation service, the first real provider boundary for Twilio Voice, a manual Twilio smoke-test runner, provider webhook/recording ingestion, a provider-neutral STT/transcript pipeline, the first concrete STT provider for OpenAI Whisper, and calling-specific UI API endpoints. It remains separate from existing chatbot/voice execution.
- `run_scenario_cli.py` - CLI test runner.

## 4. End-to-End Flow

1. User sends a `TestRunRequest` or CLI runs a Scenario YAML.
2. The `orchestrator` creates a Connection adapter (REST Chat, Voice, etc).
3. (If configured) The Connection resolves a Browser Token via `BrowserAuthManager` (Playwright background thread).
4. The `simulator` initializes the Ollama persona.
5. The `orchestrator` loops:
   - Simulator generates text.
   - Adapter sends text (or audio) to the target Chatbot/Agent.
   - Adapter parses the target's response.
6. Once max turns are hit or the goal is reached, the conversation transcript is passed to the `evaluator`.
7. `evaluator` scores the transcript using Gemini GEval metrics.
8. The result is saved to `storage` (SQLite) and returned to the user.

## 5. Component Details

### Browser Auth Manager (`app.connections.browser_auth`)
- **Purpose:** Extracts OAuth/JWT tokens or session data by launching headless Playwright browsers.
- **Dependencies:** Playwright, asyncio.
- **Processing:** Supports `intercept_pattern`, `trigger_script`, and `delete_cookies` to generically force auth token refreshes without hardcoding target implementations like Clerk.
- **Verified storage-state save:** `BrowserAuthCheck` and `BrowserAuthSaveResult` support a stricter interactive save flow. A session can now wait for configurable authentication evidence (`expected_url`, `authenticated_selector`, and/or `required_cookie`), save `storage_state` from the exact same `BrowserContext`, then launch a fresh context with that saved state and verify authentication again before reporting success. Failed fresh-context verification removes the saved state file so stale or logged-out state is not reused silently. Because Playwright's native `storage_state` captures cookies and localStorage but not sessionStorage, BrowserAuthManager augments saved state with a private `_evalforge_sessionStorage` section and restores it with `add_init_script` before navigation. This is important for Clerk sessions that look authenticated in the live login context but lose required sessionStorage data after a plain Playwright restore.
- **Option A browser auth flow:** "Open Login / Authenticate" is a setup/update action only. It launches a visible browser for the initial login or for expired/revoked saved sessions, verifies the configured auth signal, writes the auth-state file, and closes the browser. Normal REST evaluations never launch this login browser; they reuse the saved `storage_state` and the existing `browser_token` extraction flow to obtain the Bearer token in a background context.

### Rest Adapter (`app.adapters.chat.rest`)
- **Purpose:** Talks to typical REST chatbots.
- **Dependencies:** `httpx` or `requests`.
- **Processing:** Formats requests (JSON body mapping) and parses responses. Interacts with the Browser Auth Manager if a `browser_token` auth type is defined.

### User Action Engine Foundation (`app.interactive`)
- **Purpose:** Phase 1 additive foundation for future interactive user actions such as quick replies, buttons, dropdowns, forms, uploads, confirmations, dates, times, and voice DTMF.
- **Runtime status:** Phase 3 adds default-off chatbot runtime integration. Existing chatbot behavior remains the default because `enable_user_action_engine` is `False` unless explicitly enabled.
- **Modules:** `models.py` defines `InteractiveElement`, `NormalizedAgentResponse`, `UserAction`, action/element enums, and validation results. `response_understanding.py` normalizes adapter metadata or conservatively parses plain transcript text. `conversation_state.py` builds planner-ready conversation state. `capability_registry.py` declares adapter action capabilities without importing or modifying adapters. `action_validator.py` validates action shape and declared capability support with fallback action suggestions.
- **Design decision:** Phase 1 uses standard-library dataclasses/enums instead of Pydantic so the foundation has no runtime dependency load and remains safe to import in isolation.
- **Phase 2 isolated planning/execution:** `planner.py` adds `ActionProposal`, `RuleBasedFallbackPlanner`, `LLMActionPlanner`, and `UserActionEngine`. Planners propose actions only and never execute adapter calls. `action_executor.py` adds `ActionExecutor` and `ActionExecutionResult`; the executor validates every action through `ActionValidator` before calling a provided adapter surface and falls back to `SEND_TEXT` when appropriate. These modules are still not imported by runtime execution.
- **Phase 3 default-off runtime hook:** `orchestrator.py` adds `ConversationOrchestrator`, which owns per-turn chatbot decisions when the feature flag is enabled. `ScenarioExecutor._execute_chatbot()` remains a thin loop coordinator: with the flag off it runs the previous text loop; with the flag on it delegates each turn to `ConversationOrchestrator`. The orchestrator uses response normalization and the User Action Engine only when interactive content exists; otherwise it lazily imports and calls the existing `generate_next_user_turn()` path.
- **Phase 4 adapter capability layer:** `adapter_capabilities.py` defines generic `AdapterCapabilities` flags for native text, option, button, dropdown, upload, DOM click, date/time, wait, confirm/cancel, DTMF, interrupt, and transfer support. `adapter_action.py` resolves optional adapter `get_capabilities()` and `execute_action(action)` methods. Existing adapters are not required to implement either method. `ActionExecutor` now uses native `execute_action()` only when the adapter both exposes it and advertises support; otherwise it preserves the existing `send_message()` fallback behavior.

### AI Calling Agent Evaluation Foundation (`app.calling`)
- **Purpose:** Phase 1 additive foundation for evaluating existing AI calling agents. EvalForge is not building a calling agent; this subsystem captures call evidence that can later be normalized and passed to the existing evaluator.
- **Runtime status:** Not integrated. No ScenarioExecutor, chatbot, voice runtime, API, schema, browser auth, or Interactive Engine runtime paths import this subsystem.
- **Design decision:** Calling reuses the existing Scenario model in future phases and must not introduce `CallingScenario`. The subsystem stops at normalized evidence production.
- **Modules:** `models.py` defines vendor-neutral `CallSession`, `CallEvent`, `CallArtifact`, `CallRecording`, `ProviderConfig`, `CallProvider`, `CallStatus`, `CallDirection`, `NormalizedCallTranscript`, and `CallingExecutionResult`. `provider_adapter.py` defines the abstract provider contract for outbound, inbound, status, end-call, recording, event, and download operations. `artifacts.py`, `events.py`, and `session.py` provide model-only helpers. `normalizer.py` converts `NormalizedCallTranscript` into the existing `NormalizedConversation` model. `runner.py` is a non-executing shell for future coordination.
- **Provider boundary:** Future providers such as Twilio, LiveKit SIP, Vapi, Retell, Bland, and custom SIP belong under `app/calling/providers/`. Provider-specific logic must stay inside provider implementations.
- **Phase 2 lifecycle layer:** `state_machine.py` validates call transitions for created, dialing, ringing, connected, in-progress, completed, failed, busy, no-answer, cancelled, transferred, disconnected, timed-out, and error paths. `lifecycle.py` coordinates transitions, `event_publisher.py` records in-memory events, `status_tracker.py` tracks current session state, `providers/mock.py` implements a pure in-memory `MockCallProvider`, and `runner.py` now includes `CallSessionRunner` for deterministic mock call evidence and `NormalizedConversation` output. This layer performs no real calls, provider IO, STT, recording downloads, webhooks, API changes, or DeepEval execution.
- **Phase 3 provider infrastructure:** `provider_registry.py`, `provider_factory.py`, `provider_resolver.py`, `provider_loader.py`, `config.py`, and `exceptions.py` implement plugin-style provider registration and resolution. The default registry lazily registers only the in-memory mock provider. `CallSessionRunner` now resolves providers through `ProviderResolver` when no adapter is explicitly injected, while preserving direct adapter injection for tests and compatibility. No real telephony SDKs are imported.
- **Phase 4 conversation evidence layer:** `conversation_evidence.py` defines vendor-neutral `ConversationEvidence` and `EvidenceArtifact` as the universal provider output model. `artifact_store.py` and `artifact_collector.py` store/collect artifact metadata only. `evidence_builder.py` combines sessions, events, recordings, transcripts, artifacts, and RAG context into `ConversationEvidence`. `conversation_normalizer.py` converts `ConversationEvidence` into the existing `NormalizedConversation` model consumed by evaluation. `CallSessionRunner` now produces evidence first and normalizes through `ConversationNormalizer`; providers still do not create `NormalizedConversation` directly.
- **Phase 5 runtime execution pipeline:** `execution_context.py`, `session_context.py`, `execution_events.py`, `execution_result.py`, `execution_pipeline.py`, and `evaluation_runner.py` connect the approved calling components into one explicit flow: scenario -> provider resolver -> mock provider -> session runner -> conversation evidence -> conversation normalizer -> calling execution result. This phase still uses only `MockCallProvider`, does not call DeepEval or `EvaluationService`, and is not wired into existing APIs or `ScenarioExecutor`.
- **Phase 6 evaluation bridge:** `calling_result_converter.py`, `evaluation_context.py`, `evaluation_adapter.py`, and `evaluation_bridge.py` convert `CallingExecutionResult` into the existing `app.executor.ExecutionResult` shape and delegate to the existing `EvaluationService`. The bridge does not implement metrics, import DeepEval directly, duplicate RAG handling, add reporting, or change existing evaluation internals. Calling remains an execution source that feeds normalized conversation evidence into the same evaluator.
- **Phase 7 Twilio provider:** `providers/twilio.py` implements `CallProviderAdapter` for Twilio Voice with lazy/injectable Twilio client access, outbound call creation, inbound session preparation, status fetching, call ending, recording metadata mapping, event mapping, and recording path metadata. `twilio_models.py`, `twilio_events.py`, `twilio_recording.py`, and `twilio_webhook.py` keep Twilio-specific payload/status/recording/webhook logic inside the calling provider boundary. Default provider registry remains mock-only; Twilio can be registered explicitly by callers/tests. `ProviderFactory` now passes generic provider config into providers that accept it and falls back to no-arg construction for existing providers.
- **Phase 8 manual Twilio smoke test:** `manual_config.py` loads manual Twilio smoke-test settings from environment variables, `manual_runner.py` resolves `TwilioProvider`, places a real outbound call, polls status to completion or timeout, collects recording metadata, builds `ConversationEvidence`, normalizes to `NormalizedConversation`, and calls the Phase 6 evaluation bridge. `scripts/smoke_test_calling_twilio.py` is a manual CLI script. It does not start FastAPI, add UI, schedule jobs, write a database, or implement STT. Conversation evaluation requires optional `CALLING_TRANSCRIPT_JSON`; otherwise the existing evaluation path reports missing conversation evidence.
- **Phase 9 webhook and recording ingestion:** `webhook_models.py`, `webhook_handler.py`, `recording_resolver.py`, `recording_registry.py`, and `recording_ingestion.py` implement provider-neutral webhook dispatch and recording metadata ingestion. `TwilioWebhookHandler` maps Twilio status and recording callbacks to existing `CallStatus`, `CallEvent`, `CallSession`, and `CallRecording` models. Duplicate delivery is idempotent through stable provider event keys. Conversation evidence is built only through `EvidenceBuilder`; webhook handlers do not construct evidence directly. No STT, recording downloads, APIs, webhooks routes, evaluation changes, or reports were added.
- **Phase 10 STT/transcript pipeline:** `audio_metadata.py`, `transcription.py`, `transcription_provider.py`, `transcription_registry.py`, `speaker_mapper.py`, `transcript_builder.py`, and `transcript_validator.py` define a provider-neutral transcript architecture. Supported sources include provider transcripts, manual transcripts, raw STT transcripts, and future diarized transcripts. Speaker labels such as `speaker_0`, `channel_0`, `customer`, and `caller` normalize to customer/simulated user; `speaker_1`, `channel_1`, `assistant`, `agent`, and `callee` normalize to agent. TranscriptBuilder validates and converts raw transcripts into `ConversationEvidence` via `EvidenceBuilder`, then to `NormalizedConversation` via `ConversationNormalizer`. No real STT providers, API calls, downloads, routes, UI, database, or evaluation changes were added.
- **Phase 11 Whisper STT provider:** `whisper_config.py`, `whisper_models.py`, and `providers/whisper.py` implement the first concrete `TranscriptionProvider` using OpenAI Whisper behind the Phase 10 provider-neutral contract. The provider accepts local audio files, supports configurable formats such as wav/mp3/m4a/ogg, lazily imports the OpenAI SDK, and returns `RawTranscript` for the existing speaker mapping, transcript validation, evidence, and normalization flow. It has injectable client support for tests and keeps OpenAI-specific errors inside the calling STT provider boundary. No API routes, UI, database, webhooks, reports, DeepEval changes, or existing runtime integrations were added.
- **Calling UI integration:** `ui_api.py` exposes calling-specific provider metadata, credential-safe calling connection CRUD, validation, and a run endpoint under `/calling/*`. The frontend adds a separate AI Calling page, provider-specific configuration forms, masked credential editing, connection validation, run controls, status timeline, transcript viewer, recording metadata viewer, and evaluation report viewer. Calling connection setup stores provider configuration only; per-run phone targeting lives in the Run Evaluation dialog with Outbound and Inbound modes. This integration does not modify chatbot/voice connection APIs or their execution path.

## 6. AI/ML Pipeline
- **User Simulation:** Ollama local models (`llama3.1:8b`).
- **Evaluation:** Gemini API via DeepEval.
- **Voice:** Whisper (STT) and Piper/ONNX (TTS) for local voice simulation.

## 7. API Flow
- `GET /ui` - Serves frontend.
- `GET /scenarios` - Lists YAML tests.
- `POST /test-runs` - Kicks off an orchestrated test.
- `GET /test-runs/{id}` - Gets test results.
- `POST /connections/browser-auth/start` - Launches interactive login.
- `POST /connections/browser-auth/save` - Saves Playwright context (`auth-state-*.json`) only after at least one configured auth check succeeds and a fresh context restored from the saved state is also authenticated.
- `GET /connections` and `GET /connections/{id}` return a credential-safe config snapshot so the frontend can edit or re-authenticate browser-token connections without exposing stored secrets.

## 8. Database / Storage
- **Local DB:** SQLite (`eval_results.db`, `connections.db`).
- **Storage state:** JSON files in the root dir (`auth-state-Sophia_AI.json`).

## 9. Infrastructure
- Uses standard Python `venv`.
- Playwright is required for browser auth (`playwright install`).
- Ollama must be running locally.
- Requires `GEMINI_API_KEY` for evaluation.

## 10. CI/CD
- Currently manual. Pytest available in `tests/`.

## 11. Configuration
- `.env` controls settings (API keys, max turns, etc.).
- `app/config.py` parses `.env`.
- Required Secrets: `GEMINI_API_KEY`.

## 12. Commands
- **Install:** `pip install -r requirements.txt`, `playwright install`
- **Run API:** `uvicorn app.main:app --reload`
- **Run CLI:** `python run_scenario_cli.py scenarios/refund_request.yaml`
- **Sophia manual login:** `python scripts/manual_login.py`
- **Test:** `pytest`

## 13. Important Decisions
- **Playwright threading:** Playwright async API is wrapped in a dedicated `_PlaywrightThread` with its own `ProactorEventLoop` (on Windows) to prevent FastAPI `NotImplementedError` issues when launching subprocesses.
- **Generic Token extraction:** Uses `delete_cookies` and `trigger_script` instead of hardcoding specific implementations like Clerk for automatically refreshing valid sessions.
- **Browser auth setup vs evaluation:** Browser authentication setup is intentionally separate from evaluation. The UI requires Browser Token REST connections to have a Browser Login URL and saved storage-state path before saving/testing. If token extraction fails because the saved auth state is missing, expired, or revoked, the UI prompts the user to run "Open Login / Authenticate" again and overwrite the existing auth-state file.

## 14. Known Issues / Limitations
- Playwright `wait_until="networkidle"` hangs indefinitely for pages using Server-Sent Events or WebSockets. Used `domcontentloaded` + manual wait/intercept fallback.
- Test sessions will time out or fail if the stored `auth-state` JSON is expired or logged out. Re-authentication via the UI is required.
- A plain Playwright `context.storage_state()` file may be insufficient for Clerk if Clerk stores active login data in sessionStorage. Auth files saved before the augmented sessionStorage change will not contain `_evalforge_sessionStorage` and should be regenerated through the verified manual login flow.
- The current local `.venv` launcher points to a missing Python 3.11 executable, and its binary packages (`pydantic_core`, `greenlet`) do not load under the bundled Python 3.12. Syntax checks pass with bundled Python, but pytest and live Playwright login cannot run in this environment until the Python environment is repaired or recreated.

## 15. Change Log

### 2026-09-30
- Initialized `brain.md` project memory.
- Added generic token extraction capabilities (`delete_cookies`, `trigger_script`) to `BrowserAuthManager`.
- Fixed asyncio timeout issues by moving `wait_until` to `domcontentloaded`.
- Replaced blind Sophia manual login save with verified authentication capture: the script waits for the authenticated Sophia UI selector, saves from the same BrowserContext, restores in a fresh context, and reports A-D verification flags before claiming success.
- Added generic verified browser auth save support to `BrowserAuthManager` and `/connections/browser-auth/save`; callers must provide `expected_url`, `authenticated_selector`, or `required_cookie`, and failed restore verification no longer leaves a bad state file behind.
- Added augmented sessionStorage capture/restore to BrowserAuthManager so Clerk-style sessions that depend on sessionStorage can survive a brand-new Playwright context. BrowserAuthManager now strips the augmented data back to native cookies/origins for `new_context(storage_state=...)` and replays sessionStorage by origin via `add_init_script`.

### 2026-10-01
- Implemented Option A browser authentication UX: the frontend treats "Open Login / Authenticate" as setup/update only, requires Browser Token REST connections to save auth-state before normal use, and prompts for re-authentication only when saved auth-state/token extraction appears expired or invalid.
- Added credential-safe connection config responses and full connection PATCH support so existing browser-authenticated REST connections can be reopened, re-authenticated, and saved under the same connection id without exposing secret auth values.
- Completed User Action Engine Phase 1 foundation: added inactive `app/interactive/` modules for generic models, response normalization, conversation state, capability registry, and action validation, plus focused unit tests. No runtime execution flow was integrated or modified.
- Completed User Action Engine Phase 2 isolated subsystem: added `planner.py` and `action_executor.py` with rule-based planning, injectable LLM planning, action proposals, validator-backed execution, and fallback behavior. Added planner/executor unit tests. No runtime execution flow was integrated or modified.
- Completed User Action Engine Phase 3 default-off chatbot integration: added `app.interactive.orchestrator.ConversationOrchestrator`, added `enable_user_action_engine` setting defaulting to false, and kept `ScenarioExecutor._execute_chatbot()` as a thin feature-flagged coordinator. Existing text behavior remains default; interactive action planning is used only when the flag is enabled and interactive content is detected.
- Completed User Action Engine Phase 4 adapter capability layer: added optional adapter capability and action contract helpers, declared REST/browser/voice placeholder capabilities, and updated `ActionExecutor` to prefer native adapter actions only when explicitly supported while preserving fallback execution for existing adapters.
- Completed AI Calling Agent Evaluation Phase 1 foundation: added isolated `app/calling/` models, provider abstraction, session/event/artifact helpers, normalizer to `NormalizedConversation`, runner shell, and unit tests. No runtime integration or existing scenario/evaluation schemas were modified.
- Completed AI Calling Agent Evaluation Phase 2 lifecycle layer: added the in-memory call state machine, lifecycle manager, event publisher, status tracker, mock provider, call session runner, mock transcript generation, artifact location placeholders, and focused unit tests. The subsystem remains isolated and produces normalized evidence only.
- Completed AI Calling Agent Evaluation Phase 3 provider infrastructure: added plugin-style provider registry, factory, resolver, loader, generic provider config, provider exceptions, resolver-backed runner creation, and focused provider infrastructure tests. The subsystem still registers only the mock provider and remains isolated from runtime execution.
- Completed AI Calling Agent Evaluation Phase 4 conversation evidence layer: added universal `ConversationEvidence`, generic evidence artifacts, local artifact metadata store, artifact collector, evidence builder, conversation normalizer, runner evidence flow, and focused evidence/normalization tests. The calling subsystem remains isolated and evaluation still receives only `NormalizedConversation`.
- Completed AI Calling Agent Evaluation Phase 5 runtime execution pipeline: added calling execution context, session context, internal execution events, runtime execution result, execution pipeline, public runtime runner, and focused pipeline/runner/context tests. The pipeline resolves only the mock provider, produces normalized evidence, and stops before evaluation.
- Completed AI Calling Agent Evaluation Phase 6 evaluation bridge: added calling result converter, calling evaluation context, evaluation adapter, evaluation bridge, exports, and focused bridge/converter/adapter tests. The bridge reuses `EvaluationService` and keeps DeepEval/reporting/API/runtime code untouched.
- Completed AI Calling Agent Evaluation Phase 7 Twilio provider boundary: added Twilio provider implementation, Twilio status/event/recording/webhook mapping helpers, Twilio-specific models, provider factory config passing, and focused Twilio tests. No Twilio SDK is imported unless a real client must be constructed, and no existing runtime/API/evaluation paths were modified.
- Completed AI Calling Agent Evaluation Phase 8 manual Twilio smoke test: added environment-driven manual config, manual runner, and scratch smoke script that exercises Twilio outbound calling through evidence, normalization, and evaluation bridge layers. Only syntax checks were run; no real call was placed.
- Completed AI Calling Agent Evaluation Phase 9 provider webhook and recording ingestion: added provider-neutral webhook payload/result models, generic webhook dispatcher, Twilio webhook handler, recording resolver, in-memory recording registry, recording ingestion service, and focused ingestion tests. Syntax checks passed; pytest remains blocked by the local Pydantic binary environment.
- Completed AI Calling Agent Evaluation Phase 10 STT/transcript pipeline: added audio metadata, raw transcript models, transcription provider abstraction and registry, manual transcription provider, speaker mapper, transcript validator, transcript builder, and focused tests. Syntax checks passed; pytest remains blocked by the local Pydantic binary environment.
- Completed AI Calling Agent Evaluation Phase 11 Whisper STT provider: added Whisper config, Whisper provider models/errors, OpenAI Whisper transcription provider, and focused provider tests. The implementation stays behind `TranscriptionProvider`, returns `RawTranscript`, supports injectable clients, and keeps real STT integration isolated under `app/calling`. Syntax checks passed; pytest remains blocked by the local Pydantic binary environment.
- Added AI Calling UI integration: introduced `/calling/*` UI API endpoints, a separate frontend AI Calling workspace, dynamic provider forms, secure masked credential responses, connection test/save/edit/delete, calling evaluation runs through the existing calling runtime/evaluation bridge, and transcript/recording/report panels. Existing chatbot and voice UI/API flows remain separate.


## Interactive Runtime (Experimental)

Status: Experimental / Future

Purpose:
This module contains a future universal interaction architecture.

Current production chatbot evaluation DOES NOT use this module.

Production path:
Scenario
→ Adapter (Browser/REST/WebSocket)
→ Chatbot
→ Conversation
→ Evaluation
→ Report

This module is reserved for future autonomous execution research.I want you to deeply inspect my CURRENT AI Agent Evaluation project.

IMPORTANT:
DO NOT implement anything.
DO NOT modify any file.
DO NOT generate code.
DO NOT suggest a new architecture yet.
DO NOT assume anything.

Your only job right now is to understand the existing project exactly as it is.

Read the complete repository carefully, including:

- backend
- frontend
- APIs
- schemas/models
- database/storage
- scenario system
- orchestrator/execution flow
- chatbot adapters
- browser/chatbot integrations
- authentication
- voice evaluation
- AI calling evaluation
- interactive/user-action engine
- evaluator
- DeepEval integration
- reports
- RAG-related code
- configuration
- tests
- any README / architecture / brain / documentation files

Then give me a CURRENT PROJECT ANALYSIS.

I specifically need to understand:

1. What is the main purpose of this project?

2. What features are currently implemented?

3. What features are partially implemented?

4. What features are only planned/foundational and not actually used in runtime?

5. Give me the complete current architecture.

6. Give me the current end-to-end flow:
   Scenario
   → execution
   → agent
   → conversation
   → evaluation
   → result/report

7. Explain the chatbot evaluation flow in detail.

8. Explain the voice-agent evaluation flow in detail.

9. Explain the AI Calling Agent evaluation flow in detail.

10. Explain the Interactive/User Action Engine and whether it is actually connected to production runtime.

11. Explain all current adapters and what each one does.

12. Explain how real external chatbots/agents are connected.

13. Explain authentication and browser-auth flow.

14. Explain the evaluation architecture:
    - EvaluationService
    - DeepEval
    - metrics
    - LLM judge
    - NormalizedConversation
    - ExecutionResult
    - reports

15. MOST IMPORTANT — inspect everything related to RAG.

For RAG, tell me exactly:

- What RAG-related files/classes/functions currently exist?
- Where is RAG handled?
- What is `rag_context`?
- Where does `rag_context` come from?
- How does it enter the evaluation pipeline?
- Which RAG metrics currently exist?
- How are those metrics calculated?
- Does the platform currently retrieve documents itself?
- Is there any retriever?
- Is there a vector database?
- Are embeddings generated?
- Is there document ingestion?
- Is there chunking?
- Is there knowledge-base integration?
- Can we capture retrieved context from the real chatbot?
- Does the evaluator currently know what chunks the real chatbot retrieved?
- Is RAG evaluation currently real retrieval evaluation, or only evaluation against supplied reference context?
- How does RAG work for chatbot evaluation?
- How does RAG work for voice/calling evaluation?
- What RAG-related data is stored in results/reports?

16. Trace RAG through the code end-to-end.

Show:

Scenario / Input
    ↓
RAG context/evidence
    ↓
Execution
    ↓
NormalizedConversation
    ↓
EvaluationService
    ↓
RAG metrics
    ↓
Result
    ↓
Report / Storage

For every step, mention the actual file, class and function involved.

17. Identify any RAG-related limitations, TODOs, placeholders, dead code, duplicate implementations, or architecture inconsistencies.

18. Tell me what parts of the existing architecture are reusable if we later build a proper universal RAG Evaluation capability.

But DO NOT design that new capability yet.

19. Give me the important folder/file tree with a one-line responsibility for each relevant file.

20. Finally provide a section:

"CURRENT STATE BEFORE RAG EVALUATION DEVELOPMENT"

In that section clearly separate:

A. Already implemented and working
B. Implemented but limited
C. Foundation exists but not fully integrated
D. Missing completely
E. Existing components that can be reused for future RAG evaluation

IMPORTANT:
Base every conclusion on actual repository code.

If documentation disagrees with code, trust the CURRENT CODE and explicitly mention the mismatch.

Do not make assumptions.

Do not change anything.

This is an inspection-only task.

I will use your analysis to decide what RAG Evaluation functionality should be built next.