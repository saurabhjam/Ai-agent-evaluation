import asyncio
import logging
from app.executor import ScenarioExecutor
from app.schemas import TestScenario, Persona
from app.models.connection import AgentConnection
from app.evaluation_service import EvaluationService

logging.basicConfig(level=logging.INFO)

scenario = TestScenario(
    scenario_id="test_voice_trace",
    description="Trace why LiveKit is failing",
    persona=Persona(
        name="Test",
        goal="Say hello and ask for a refund please",
        tone="neutral",
        edge_case=None
    ),
    agent={"channel": "voice"},
    pass_threshold=0.5
)

connection = AgentConnection(
    id="test_conn",
    name="Test Connection",
    agent_type="voice",
    adapter="livekit",
    type="api",
    config={
        "url": "ws://localhost:7880",
        "api_key": "devkey",
        "api_secret": "secret",
        "agent_name": "test-agent"
    }
)

executor = ScenarioExecutor()
result = executor.execute(connection, scenario)
print("ExecutionResult transcript length:", len(result.transcript or []))
print("VoiceConversation turns:", len(result.voice_conversation.turns) if result.voice_conversation else "No vc")

eval_service = EvaluationService()
eval_result = eval_service.evaluate(result, scenario)
print("Evaluation success:", eval_result.success)
print("Evaluation error:", eval_result.error)
