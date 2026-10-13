import pytest
from unittest.mock import MagicMock, patch
from app.executor import ScenarioExecutor
from app.models.connection import AgentConnection
from app.schemas import TestScenario, AgentConfig, Persona

@pytest.fixture
def base_scenario():
    return TestScenario(
        scenario_id="loop_test",
        agent=AgentConfig(channel="chatbot", adapter="rest"),
        persona=Persona(name="Loop Tester", goal="Test loops", tone="neutral"),
        max_turns=3
    )

@patch("app.executor.generate_next_user_turn")
@patch("app.executor.ConnectionManager")
def test_conversation_loop_detected_stops_immediately(mock_cm_class, mock_generate, base_scenario):
    mock_cm = mock_cm_class.return_value
    mock_adapter = MagicMock()
    mock_cm.create_adapter.return_value = mock_adapter

    # Generate same message repeatedly
    mock_generate.return_value = {"message": "Hello!"}
    
    conn = AgentConnection(id="1", name="Test", type="chatbot", adapter="rest")
    executor = ScenarioExecutor(mock_cm)
    
    result = executor.execute(conn, base_scenario)
    
    assert result.success
    # Should only run 1 time (first time it's sent, second time it detects loop and stops before sending)
    assert mock_adapter.send_message.call_count == 1

@patch("app.executor.generate_next_user_turn")
@patch("app.executor.ConnectionManager")
def test_goal_achieved_stops_immediately(mock_cm_class, mock_generate, base_scenario):
    mock_cm = mock_cm_class.return_value
    mock_adapter = MagicMock()
    mock_cm.create_adapter.return_value = mock_adapter

    mock_generate.side_effect = [
        {"message": "Hello!"},
        {"message": "[END_CONVERSATION]"}
    ]
    
    conn = AgentConnection(id="1", name="Test", type="chatbot", adapter="rest")
    executor = ScenarioExecutor(mock_cm)
    
    result = executor.execute(conn, base_scenario)
    
    assert result.success
    assert mock_adapter.send_message.call_count == 1

@patch("app.executor.generate_next_user_turn")
@patch("app.executor.ConnectionManager")
def test_goal_not_achieved_continues_until_max_turns(mock_cm_class, mock_generate, base_scenario):
    mock_cm = mock_cm_class.return_value
    mock_adapter = MagicMock()
    mock_cm.create_adapter.return_value = mock_adapter

    # Different messages so no loop
    mock_generate.side_effect = [
        {"message": "Hello!"},
        {"message": "How are you?"},
        {"message": "Goodbye!"},
        {"message": "Should not reach here"}
    ]
    
    conn = AgentConnection(id="1", name="Test", type="chatbot", adapter="rest")
    executor = ScenarioExecutor(mock_cm)
    
    result = executor.execute(conn, base_scenario)
    
    assert result.success
    # Should run exactly max_turns (3) times
    assert mock_adapter.send_message.call_count == 3
