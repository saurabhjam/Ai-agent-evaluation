import pytest
from unittest.mock import MagicMock
from app.models.voice import VoiceConversation, VoiceSession, SessionStatus, VoiceTurn, Speaker, VoiceEvent, VoiceEventType
from app.voice.converter import voice_to_normalized_conversation
from app.evaluation_service import EvaluationService
from app.executor import ExecutionResult
from app.schemas import TestScenario, Persona

def test_regression_no_conversation_evidence():
    # 1. Create a VoiceConversation with transcript events but empty VoiceTurns
    # Wait, the prompt says: "when LiveKit produces user and agent transcript events"
    vc = VoiceConversation(
        session=VoiceSession(session_id="test", status=SessionStatus.completed),
        turns=[
            VoiceTurn(speaker=Speaker.user, text="Hello"),
            VoiceTurn(speaker=Speaker.agent, text="Hi there"),
        ],
        events=[]
    )
    
    # 2. Convert to NormalizedConversation
    normalized = voice_to_normalized_conversation(vc)
    
    # 3. Create ExecutionResult
    exec_result = ExecutionResult(
        success=True,
        connection_id="test",
        agent_type="voice",
        adapter="livekit",
        transcript=normalized.messages,
        voice_conversation=vc,
        started_at="2024-01-01T00:00:00Z",
        completed_at="2024-01-01T00:01:00Z"
    )
    
    # 4. Evaluate
    scenario = TestScenario(
        scenario_id="test",
        description="test",
        persona=Persona(name="test", goal="test goal 123", tone="neutral", edge_case=""),
        agent={"channel": "voice"},
        pass_threshold=0.5
    )
    eval_service = EvaluationService()
    result = eval_service.evaluate(exec_result, scenario)
    
    # The result should NOT be "No conversation evidence was captured."
    assert result.error != "No conversation evidence was captured."
    assert len(result.conversation) == 2
