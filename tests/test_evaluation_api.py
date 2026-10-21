import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app
from app.connections.storage import repository
from app.models.connection import AgentConnection, AgentType
from app.executor import ExecutionResult
from app.evaluation_service import EvaluationResult, ConversationTurn

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_repository(tmp_path, monkeypatch):
    monkeypatch.setattr("app.connections.storage.settings.db_path", str(tmp_path / "evaluation_api.db"))
    repository.clear()
    yield

@pytest.fixture
def mock_scenario_file(tmp_path):
    import yaml
    scenario_data = {
        "scenario_id": "test_scenario_api",
        "agent": {"channel": "chatbot", "adapter": "fake"},
        "persona": {"name": "Test", "goal": "Testing goal length requirement", "tone": "Test"},
        "max_turns": 2,
        "pass_threshold": 0.5
    }
    file_path = tmp_path / "test_scenario.yaml"
    with open(file_path, "w") as f:
        yaml.dump(scenario_data, f)
    return str(file_path)

def test_evaluate_connection_not_found(mock_scenario_file):
    response = client.post("/connections/non_existent/evaluate", json={"scenario_path": mock_scenario_file})
    assert response.status_code == 404
    assert "Connection not found" in response.json()["detail"]

def test_evaluate_connection_disabled(mock_scenario_file):
    conn = AgentConnection(id="disabled_conn", name="Test", type="chatbot", adapter="fake", enabled=False)
    repository.save(conn)
    
    response = client.post(f"/connections/{conn.id}/evaluate", json={"scenario_path": mock_scenario_file})
    assert response.status_code == 400
    assert "disabled" in response.json()["detail"]

def test_evaluate_scenario_not_found():
    conn = AgentConnection(id="conn_1", name="Test", type="chatbot", adapter="fake")
    repository.save(conn)
    
    response = client.post(f"/connections/{conn.id}/evaluate", json={"scenario_path": "nonexistent.yaml"})
    assert response.status_code == 404
    assert "Scenario not found" in response.json()["detail"]

@patch("app.connections.api.ScenarioExecutor")
@patch("app.connections.api.EvaluationService")
def test_successful_chatbot_evaluation(mock_eval_svc, mock_executor, mock_scenario_file):
    conn = AgentConnection(id="conn_chatbot", name="Test Chatbot", type="chatbot", adapter="fake")
    repository.save(conn)
    
    mock_exec_instance = MagicMock()
    mock_executor.return_value = mock_exec_instance
    mock_exec_result = ExecutionResult(
        success=True, connection_id=conn.id, agent_type="chatbot", adapter="fake", 
        started_at="start", completed_at="end", transcript=[{"role":"user", "content":"hello"}]
    )
    mock_exec_instance.execute.return_value = mock_exec_result
    
    mock_eval_instance = MagicMock()
    mock_eval_svc.return_value = mock_eval_instance
    
    mock_eval_result = EvaluationResult(
        success=True, agent_id=conn.id, agent_type="chatbot", adapter="fake", scenario_id="test_scenario_api",
        overall_score=1.0, passed=True, metrics=[], created_at="now", session_id="sess_1",
        conversation=[ConversationTurn(speaker="user", message="hello"), ConversationTurn(speaker="agent", message="hi")]
    )
    mock_eval_instance.evaluate.return_value = mock_eval_result
    
    response = client.post(f"/connections/{conn.id}/evaluate", json={"scenario_path": mock_scenario_file})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["agent_type"] == "chatbot"
    assert data["overall_score"] == 1.0
    assert data["session_id"] == "sess_1"
    assert data["voice_metrics"] is None
    assert "conversation" in data
    assert isinstance(data["conversation"], list)
    assert len(data["conversation"]) == 2
    assert data["conversation"][0]["speaker"] == "user"
    assert data["conversation"][0]["message"] == "hello"
    assert data["conversation"][1]["speaker"] == "agent"
    assert data["conversation"][1]["message"] == "hi"
    
    # Credentials shouldn't be returned (not explicitly in eval result anyway)
    assert "api_key" not in data
    
    # Verify DeepEval isn't called directly by API
    # Since we mocked EvaluationService and it didn't call DeepEval directly here, it's satisfied

@patch("app.connections.api.ScenarioExecutor")
@patch("app.connections.api.EvaluationService")
def test_successful_voice_evaluation(mock_eval_svc, mock_executor, mock_scenario_file):
    conn = AgentConnection(id="conn_voice", name="Test Voice", type="voice", adapter="livekit")
    repository.save(conn)
    
    mock_exec_instance = MagicMock()
    mock_executor.return_value = mock_exec_instance
    mock_exec_result = ExecutionResult(
        success=True, connection_id=conn.id, agent_type="voice", adapter="livekit", 
        started_at="start", completed_at="end", transcript=[{"role":"user", "content":"hello"}]
    )
    mock_exec_instance.execute.return_value = mock_exec_result
    
    mock_eval_instance = MagicMock()
    mock_eval_svc.return_value = mock_eval_instance
    
    mock_eval_result = EvaluationResult(
        success=True, agent_id=conn.id, agent_type="voice", adapter="livekit", scenario_id="test_scenario_api",
        overall_score=0.8, passed=True, metrics=[], voice_metrics=[{"name": "Latency", "score": 1.0, "reason": "Fast", "passed": True}], created_at="now", session_id="sess_2",
        conversation=[ConversationTurn(speaker="user", message="voice hello"), ConversationTurn(speaker="agent", message="voice hi")]
    )
    mock_eval_instance.evaluate.return_value = mock_eval_result
    
    response = client.post(f"/connections/{conn.id}/evaluate", json={"scenario_path": mock_scenario_file})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["agent_type"] == "voice"
    assert data["voice_metrics"] is not None
    assert len(data["voice_metrics"]) == 1
    assert "conversation" in data
    assert len(data["conversation"]) == 2
    assert data["conversation"][0]["speaker"] == "user"
    assert data["conversation"][0]["message"] == "voice hello"
    assert data["conversation"][1]["speaker"] == "agent"
    assert data["conversation"][1]["message"] == "voice hi"

@patch("app.connections.api.ScenarioExecutor")
@patch("app.connections.api.EvaluationService")
def test_execution_failure(mock_eval_svc, mock_executor, mock_scenario_file):
    conn = AgentConnection(id="conn_fail", name="Test Fail", type="chatbot", adapter="fake")
    repository.save(conn)
    
    mock_exec_instance = MagicMock()
    mock_executor.return_value = mock_exec_instance
    mock_exec_result = ExecutionResult(
        success=False, connection_id=conn.id, agent_type="chatbot", adapter="fake", 
        started_at="start", completed_at="end", error="Network Error"
    )
    mock_exec_instance.execute.return_value = mock_exec_result
    
    mock_eval_instance = MagicMock()
    mock_eval_svc.return_value = mock_eval_instance
    
    mock_eval_result = EvaluationResult(
        success=False, agent_id=conn.id, agent_type="chatbot", adapter="fake", scenario_id="test_scenario_api",
        error="Network Error", created_at="now"
    )
    mock_eval_instance.evaluate.return_value = mock_eval_result
    
    response = client.post(f"/connections/{conn.id}/evaluate", json={"scenario_path": mock_scenario_file})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "Network Error" in data["error"]
    assert "conversation" in data
    assert data["conversation"] == []

@patch("app.connections.api.ScenarioExecutor")
def test_evaluation_failure(mock_executor, mock_scenario_file):
    conn = AgentConnection(id="conn_eval_fail", name="Test Eval Fail", type="chatbot", adapter="fake")
    repository.save(conn)
    
    mock_exec_instance = MagicMock()
    mock_executor.return_value = mock_exec_instance
    mock_exec_result = ExecutionResult(
        success=True, connection_id=conn.id, agent_type="chatbot", adapter="fake", 
        started_at="start", completed_at="end", transcript=[{"role": "user", "content": "hello"}]
    )
    mock_exec_instance.execute.return_value = mock_exec_result
    
    # Do not mock EvaluationService here; let it fail normally or throw
    with patch("app.evaluation_service.evaluate_transcript", side_effect=Exception("DeepEval Crash")):
        response = client.post(f"/connections/{conn.id}/evaluate", json={"scenario_path": mock_scenario_file})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "DeepEval Crash" in data["error"]
        assert "conversation" in data
        assert data["conversation"] == []
