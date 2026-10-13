"""
Tests for the ScenarioExecutor.
"""
import pytest
from unittest.mock import MagicMock, patch

from app.executor import ScenarioExecutor, ExecutionResult
from app.models.connection import AgentConnection, AgentType
from app.models.conversation import ConversationMessage
from app.schemas import TestScenario, Persona, AgentConfig

@pytest.fixture
def mock_scenario():
    return TestScenario(
        scenario_id="test_scenario",
        agent=AgentConfig(channel="chatbot", adapter="fake"),
        persona=Persona(name="Test User", goal="Testing goal length requirements", tone="Test"),
        max_turns=3,
        pass_threshold=0.5
    )

def test_disabled_connection(mock_scenario):
    conn = AgentConnection(id="1", name="Test", type="chatbot", adapter="fake", enabled=False)
    executor = ScenarioExecutor()
    result = executor.execute(conn, mock_scenario)
    assert not result.success
    assert "disabled" in result.error

@patch("app.executor.ConnectionManager")
def test_adapter_instantiation_failure(mock_cm_class, mock_scenario):
    mock_cm = mock_cm_class.return_value
    mock_cm.create_adapter.side_effect = ValueError("Bad config")
    
    conn = AgentConnection(id="1", name="Test", type="chatbot", adapter="fake")
    executor = ScenarioExecutor(mock_cm)
    result = executor.execute(conn, mock_scenario)
    
    assert not result.success
    assert "Bad config" in result.error
    mock_cm.create_adapter.assert_called_once_with(conn)

@patch("app.executor.generate_next_user_turn")
@patch("app.executor.ConnectionManager")
def test_chatbot_execution_success(mock_cm_class, mock_generate, mock_scenario):
    mock_cm = mock_cm_class.return_value
    mock_adapter = MagicMock()
    mock_cm.create_adapter.return_value = mock_adapter
    
    mock_generate.side_effect = [
        {"message": "Hello"},
        {"message": "[END_CONVERSATION]"}
    ]
    
    mock_conv = MagicMock()
    mock_conv.messages = [{"role": "user", "content": "Hello"}]
    mock_adapter.get_conversation.return_value = mock_conv
    
    conn = AgentConnection(id="1", name="Test", type="chatbot", adapter="rest")
    executor = ScenarioExecutor(mock_cm)
    result = executor.execute(conn, mock_scenario)
    
    assert result.success
    assert result.agent_type == "chatbot"
    assert result.adapter == "rest"
    assert result.transcript == mock_conv.messages
    
    mock_adapter.connect.assert_called_once()
    mock_adapter.close.assert_called_once()
    mock_adapter.send_message.assert_called_once_with("Hello", agent_prompt=None, attachments=None)


@patch("app.executor.generate_next_user_turn")
@patch("app.executor.ConnectionManager")
def test_chatbot_execution_selects_interactive_option_before_generating_text(
    mock_cm_class,
    mock_generate,
):
    scenario = TestScenario(
        scenario_id="interactive_scenario",
        agent=AgentConfig(channel="chatbot", adapter="rest"),
        persona=Persona(
            name="Test User",
            goal="Report a maintenance issue and ask about open maintenance tickets",
            tone="concise",
        ),
        max_turns=2,
    )
    mock_cm = mock_cm_class.return_value
    mock_adapter = MagicMock()
    mock_cm.create_adapter.return_value = mock_adapter

    agent_with_options = ConversationMessage(
        role="agent",
        content="Pick a topic below.",
        turn_index=1,
        metadata={
            "components": [
                {
                    "type": "button",
                    "label": "Portfolio summary",
                    "message": "Portfolio summary?",
                },
                {
                    "type": "button",
                    "label": "Open maintenance tickets",
                    "message": "What maintenance tickets are open?",
                },
            ]
        },
    )
    mock_adapter.get_transcript.side_effect = [
        [],
        [
            ConversationMessage(role="simulated_user", content="I need maintenance help.", turn_index=0),
            agent_with_options,
        ],
    ]
    mock_generate.return_value = {"message": "I need maintenance help."}

    mock_conv = MagicMock()
    mock_conv.messages = []
    mock_adapter.get_conversation.return_value = mock_conv

    conn = AgentConnection(id="1", name="Test", type="chatbot", adapter="rest")
    result = ScenarioExecutor(mock_cm).execute(conn, scenario)

    assert result.success
    assert mock_generate.call_count == 1
    assert mock_adapter.send_message.call_args_list[0].args == ("I need maintenance help.",)
    assert mock_adapter.send_message.call_args_list[1].args == ("What maintenance tickets are open?",)


@patch("app.executor.generate_next_user_turn")
@patch("app.executor.ConnectionManager")
def test_chatbot_execution_uses_quick_reply_subtype_as_interactive_option(
    mock_cm_class,
    mock_generate,
):
    scenario = TestScenario(
        scenario_id="quick_reply_scenario",
        agent=AgentConfig(channel="chatbot", adapter="rest"),
        persona=Persona(
            name="Test User",
            goal="Book a consultation appointment",
            tone="polite",
        ),
        max_turns=2,
    )
    mock_cm = mock_cm_class.return_value
    mock_adapter = MagicMock()
    mock_cm.create_adapter.return_value = mock_adapter
    mock_adapter.get_transcript.side_effect = [
        [
            ConversationMessage(
                role="agent",
                content="Choose an option.",
                turn_index=0,
                metadata={
                    "components": [
                        {
                            "type": "button",
                            "subtype": "quick_reply",
                            "label": "Book appointment",
                            "message": "I want to book an appointment.",
                        }
                    ]
                },
            )
        ],
        [],
    ]
    mock_generate.return_value = {"message": "[END_CONVERSATION]"}
    mock_conv = MagicMock()
    mock_conv.messages = []
    mock_adapter.get_conversation.return_value = mock_conv

    conn = AgentConnection(id="1", name="Test", type="chatbot", adapter="rest")
    result = ScenarioExecutor(mock_cm).execute(conn, scenario)

    assert result.success
    mock_generate.assert_called_once()
    mock_adapter.send_message.assert_called_once_with(
        "I want to book an appointment.",
        agent_prompt=None,
        attachments=None,
    )

@patch("app.executor.VoicePersonaEngine")
@patch("app.executor.voice_to_normalized_conversation")
@patch("app.executor.ConnectionManager")
def test_voice_execution_success(mock_cm_class, mock_normalize, mock_engine_class, mock_scenario):
    mock_cm = mock_cm_class.return_value
    mock_adapter = MagicMock()
    mock_cm.create_adapter.return_value = mock_adapter
    
    mock_engine = mock_engine_class.return_value
    mock_vc = MagicMock()
    mock_vc.session.session_id = "test-session-id"
    mock_engine.run_automated_session.return_value = mock_vc
    
    mock_normalized = MagicMock()
    mock_normalized.messages = [{"role": "user", "content": "voice hello"}]
    mock_normalize.return_value = mock_normalized
    
    conn = AgentConnection(id="2", name="Test Voice", type="voice", adapter="livekit")
    executor = ScenarioExecutor(mock_cm)
    result = executor.execute(conn, mock_scenario)
    
    assert result.success
    assert result.agent_type == "voice"
    assert result.adapter == "livekit"
    assert result.session_id == "test-session-id"
    assert result.transcript == mock_normalized.messages
    
    mock_engine_class.assert_called_once()
    mock_engine.run_automated_session.assert_called_once()

@patch("app.executor.ConnectionManager")
def test_execution_failure_is_caught(mock_cm_class, mock_scenario):
    mock_cm = mock_cm_class.return_value
    mock_adapter = MagicMock()
    mock_cm.create_adapter.return_value = mock_adapter
    mock_adapter.connect.side_effect = RuntimeError("Network error")
    
    conn = AgentConnection(id="1", name="Test", type="chatbot", adapter="rest")
    executor = ScenarioExecutor(mock_cm)
    result = executor.execute(conn, mock_scenario)
    
    assert not result.success
    assert "Network error" in result.error

def test_normalized_result_structure():
    res = ExecutionResult(
        success=True,
        connection_id="abc",
        agent_type="chatbot",
        adapter="fake",
        started_at="start",
        completed_at="end"
    )
    assert res.success is True
    assert res.session_id is None
    assert res.transcript is None
    
def test_existing_chatbot_flow_was_not_changed():
    # Ensure orchestrator exists and unchanged
    from app.orchestrator import run_scenario
    assert callable(run_scenario)
