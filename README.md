<<<<<<< HEAD
# Voice Agent & Chatbot Evaluation — POC

A minimal, runnable proof of concept for the platform described in the R&D
report: a simulated user (Ollama) has a conversation with your chatbot,
and DeepEval metrics (judged by Gemini's free tier) score the transcript.
Every request is validated with Pydantic before any LLM call happens.

This POC covers the **chatbot channel** only, per the roadmap ("build and
validate the shared judge logic on text first, extend to voice after") —
the orchestrator is written so a voice adapter can plug in later without
touching the evaluator.

## What's included

```
app/
  config.py        — settings loaded from .env
  schemas.py        — Pydantic models = backend validation layer
  simulator.py       — Ollama-driven simulated user
  chatbot_client.py    — HTTP adapter to the chatbot under test
  evaluator.py       — DeepEval metrics (GEval + Hallucination) via Gemini
  orchestrator.py      — runs the conversation loop, then evaluates it
  storage.py         — SQLite persistence for run results
  main.py           — FastAPI app tying it together
scenarios/
  refund_request.yaml    — example scenario with RAG context (hallucination check enabled)
  booking_change.yaml    — example scenario with a mid-conversation edge case
run_scenario_cli.py     — convenience script: load a YAML scenario, run it, print results
```

## Setup

1. **Install dependencies**
   ```bash
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Get a free Gemini API key** from Google AI Studio, then copy the env template:
   ```bash
   cp .env.example .env
   # edit .env: set GEMINI_API_KEY
   ```

3. **Pull an Ollama model** for the simulated user:
   ```bash
   ollama pull llama3.1:8b
   ```

4. **Configure your chatbot endpoint in the scenario YAML.** The Generic REST Adapter is configured through the scenario YAML file (e.g., `scenarios/real_company_chat.yaml`).
   The real company chatbot endpoint is configured under `agent -> adapter: rest -> config`:
   ```yaml
   agent:
     channel: chatbot
     adapter: rest
     config:
       base_url: "http://127.0.0.1:8000"
       session:
         method: POST
         path: "/api/v1/chat"
   ```

## Run it

```bash
uvicorn app.main:app --reload
```

In another terminal:

```bash
python run_scenario_cli.py scenarios/refund_request.yaml
```

Or call the API directly:

```bash
curl -X POST http://localhost:8000/test-runs \
  -H "Content-Type: application/json" \
  -d @- <<'EOF'
{
  "scenario": {
    "scenario_id": "quick_test",
    "channel": "chatbot",
    "persona": {
      "name": "Alex",
      "goal": "Find out if the product ships internationally",
      "tone": "curious, brief messages"
    },
    "max_turns": 4,
    "pass_threshold": 0.6
  }
}
EOF
```

Fetch a past run:
```bash
curl http://localhost:8000/test-runs/<run_id>
```

## Where backend validation happens

`schemas.py` is the enforcement point. Examples of what gets rejected
before any LLM call runs:
- `max_turns` outside `MIN_TURNS_PER_RUN`–`MAX_TURNS_PER_RUN` (set in `.env`)
- `persona.goal` shorter than 10 characters or a placeholder like `"n/a"`
- `pass_threshold` outside `0.0–1.0`
- Missing required persona fields

Try it: POST a scenario with `"max_turns": 500` and you'll get a 422 with
the validation error, not a 200 that silently clamps the value.

## Where DeepEval fits in

`evaluator.py` builds two `GEval` metrics (Goal Completion, Persona/Tone
Adherence) with explicit `evaluation_steps` — structured rubrics reduce
judge score variance, which matters more than model size once you're on
Gemini. If a scenario includes `rag_context`, a `HallucinationMetric` is
added automatically.

To add a new metric (e.g. a safety/policy check), define another `GEval`
in `_build_metrics()` and append it to the returned list — nothing else
needs to change.

## Next steps toward the full platform (see R&D report, Section 10)

1. Swap SQLite for Postgres, run scenarios via Celery/Temporal in parallel
2. Add a voice adapter (Twilio + Whisper/Piper) alongside `chatbot_client.py`
3. Add the audio-layer metrics (latency, interruption detection, WER)
4. Build the dashboard and regression-tracking view over `list_runs()`
5. Wire a GitHub Action to call `/test-runs` on every deploy and fail the
   build if `overall_score` drops below the previous run's baseline
=======
# Ai-agent-evaluation
>>>>>>> aecbe632135ecce7f6de8cb4964a5b6db394c15d
