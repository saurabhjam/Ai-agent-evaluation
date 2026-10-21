from app.connections.manager import ConnectionManager
from app.connections.registry import AdapterRegistry
import app.executor as executor_module
from app.executor import ScenarioExecutor
from app.models.connection import AgentConnection, AgentType
from app.models.conversation import ConversationMessage, NormalizedConversation
from app.schemas import AgentConfig, Persona, TestScenario
from app.session import BrowserSession, EvaluationSession


def _browser_session(connection):
    return BrowserSession(
        storage_state=None,
        connection_config=connection.config,
    )


def test_connection_manager_passes_session_to_rest_adapter():
    connection = AgentConnection(
        id="session-rest",
        name="Session REST",
        type=AgentType.chatbot,
        adapter="rest",
        config={"endpoint": "https://example.test/chat"},
    )
    browser_session = _browser_session(connection)
    session = EvaluationSession.create(connection, browser_session=browser_session)

    adapter = ConnectionManager().create_adapter(
        connection,
        evaluation_session=session,
    )

    assert adapter.evaluation_session is session
    assert session.connection is connection
    assert session.browser_session is browser_session
    assert session.auth_provider is adapter.auth_provider


def test_evaluation_session_cleanup_delegates_to_auth_provider():
    class AuthProvider:
        def __init__(self):
            self.cleaned = False

        def cleanup(self):
            self.cleaned = True

    connection = AgentConnection(
        id="session-cleanup",
        name="Session Cleanup",
        type=AgentType.chatbot,
        adapter="fake",
        config={},
    )
    provider = AuthProvider()
    session = EvaluationSession.create(
        connection,
        browser_session=_browser_session(connection),
    )
    session.auth_provider = provider

    session.cleanup()

    assert provider.cleaned is True


def test_registry_keeps_config_only_factories_compatible_with_session():
    registry = AdapterRegistry()
    registry.register(
        "chatbot",
        "custom",
        lambda cfg: {"received": cfg},
    )
    connection = AgentConnection(
        id="session-custom",
        name="Session Custom",
        type=AgentType.chatbot,
        adapter="custom",
        config={"mode": "legacy"},
    )
    session = EvaluationSession.create(
        connection,
        browser_session=_browser_session(connection),
    )

    adapter = registry.create(connection, evaluation_session=session)

    assert adapter == {"received": {"mode": "legacy"}}


def test_scenario_executor_creates_one_browser_session_per_evaluation(monkeypatch):
    created_sessions = []

    class CountingBrowserSession:
        def __init__(self, storage_state, connection_config):
            self.storage_state = storage_state
            self.connection_config = connection_config
            created_sessions.append(self)

    class Adapter:
        def __init__(self):
            self.transcript = []

        def connect(self):
            pass

        def send_message(self, message, agent_prompt=None, attachments=None):
            self.transcript.append(
                ConversationMessage(
                    role="simulated_user",
                    content=message,
                    turn_index=len(self.transcript),
                )
            )
            return "ok"

        def get_conversation(self):
            return NormalizedConversation(
                run_id="run",
                session_id="session",
                channel="chatbot",
                messages=self.transcript,
            )

        def close(self):
            pass

    class Manager:
        def __init__(self):
            self.evaluation_session = None
            self.adapter = Adapter()

        def create_adapter(self, connection, evaluation_session=None):
            self.evaluation_session = evaluation_session
            return self.adapter

    monkeypatch.setattr(executor_module, "BrowserSession", CountingBrowserSession)
    manager = Manager()
    connection = AgentConnection(
        id="executor-session",
        name="Executor Session",
        type=AgentType.chatbot,
        adapter="fake",
        config={"auth": {"storage_state": "state.json"}},
    )
    scenario = TestScenario(
        scenario_id="executor_session",
        agent=AgentConfig(channel="chatbot", adapter="fake", config={}),
        persona=Persona(name="Ava", goal="Say hello to the chatbot", tone="polite"),
        steps=[{"send": "hello"}],
    )

    result = ScenarioExecutor(manager).execute(connection, scenario)

    assert result.success is True
    assert len(created_sessions) == 1
    assert manager.evaluation_session.browser_session is created_sessions[0]
    assert created_sessions[0].storage_state == "state.json"


def test_scenario_executor_closes_browser_session_when_adapter_creation_fails(monkeypatch):
    sessions = []

    class BrowserSessionThatTracksClose:
        def __init__(self, storage_state, connection_config):
            self.closed = False
            sessions.append(self)

        def close(self):
            self.closed = True

    class FailingManager:
        def create_adapter(self, connection, evaluation_session=None):
            raise TimeoutError("Browser token retrieval timed out during navigation")

    monkeypatch.setattr(executor_module, "BrowserSession", BrowserSessionThatTracksClose)
    connection = AgentConnection(
        id="executor-timeout",
        name="Timeout REST",
        type=AgentType.chatbot,
        adapter="rest",
        config={"endpoint": "https://example.test/chat"},
    )
    scenario = TestScenario(
        scenario_id="executor_timeout",
        agent=AgentConfig(channel="chatbot", adapter="rest", config={}),
        persona=Persona(name="Ava", goal="Ask a question", tone="polite"),
    )

    result = ScenarioExecutor(FailingManager()).execute(connection, scenario)

    assert result.success is False
    assert "Browser token retrieval timed out during navigation" in result.error
    assert len(sessions) == 1 and sessions[0].closed
