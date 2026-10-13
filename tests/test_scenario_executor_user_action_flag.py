from unittest.mock import MagicMock, patch

from app.executor import ScenarioExecutor
from app.models.connection import AgentConnection
from app.schemas import AgentConfig, Persona, TestScenario


def _scenario():
    return TestScenario(
        scenario_id="flag_test",
        agent=AgentConfig(channel="chatbot", adapter="rest"),
        persona=Persona(name="Tester", goal="Testing goal length requirements", tone="neutral"),
        max_turns=2,
    )


def _connection():
    return AgentConnection(id="1", name="Test", type="chatbot", adapter="rest")


def _adapter():
    adapter = MagicMock()
    adapter.get_transcript.return_value = []
    conversation = MagicMock()
    conversation.messages = []
    adapter.get_conversation.return_value = conversation
    return adapter


@patch("app.executor.settings")
@patch("app.executor.generate_next_user_turn")
def test_feature_flag_off_uses_existing_text_loop(mock_generate, mock_settings):
    mock_settings.enable_user_action_engine = False
    adapter = _adapter()
    manager = MagicMock()
    manager.create_adapter.return_value = adapter
    mock_generate.side_effect = [{"message": "Hello"}, {"message": "[END_CONVERSATION]"}]

    result = ScenarioExecutor(manager).execute(_connection(), _scenario())

    assert result.success is True
    assert mock_generate.call_count == 2
    adapter.send_message.assert_called_once_with("Hello", agent_prompt=None, attachments=None)


@patch("app.executor.settings")
@patch("app.executor.ConversationOrchestrator")
@patch("app.executor.generate_next_user_turn")
def test_feature_flag_on_delegates_turns_to_conversation_orchestrator(
    mock_generate,
    mock_orchestrator_class,
    mock_settings,
):
    mock_settings.enable_user_action_engine = True
    adapter = _adapter()
    manager = MagicMock()
    manager.create_adapter.return_value = adapter
    orchestrator = mock_orchestrator_class.return_value
    orchestrator.run_turn.side_effect = [
        MagicMock(should_continue=True),
        MagicMock(should_continue=False),
    ]

    result = ScenarioExecutor(manager).execute(_connection(), _scenario())

    assert result.success is True
    mock_generate.assert_not_called()
    assert orchestrator.run_turn.call_count == 2
