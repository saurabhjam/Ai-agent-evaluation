from app.connections.api import (
    AgentConnectionResponse,
    _merge_backend_validation_patch,
    _merge_backend_validation_into_scenario,
)
from app.models.connection import AgentConnection
from app.schemas import AgentConfig, Persona, TestScenario


def _scenario():
    return TestScenario(
        scenario_id="backend-connection",
        agent=AgentConfig(channel="chatbot", adapter="rest", config={}),
        persona=Persona(name="Rahul", goal="Complete backend validation", tone="polite"),
        backend_validation=[
            {
                "name": "Verify Ticket",
                "backend": "primary-rest",
                "type": "rest",
                "request": {"url": "/tickets/1"},
                "expect": {"$.status": {"equals": "OPEN"}},
            }
        ],
    )


def test_connection_response_redacts_backend_validation_secrets():
    connection = AgentConnection(
        id="conn_1",
        name="Agent",
        type="chatbot",
        adapter="rest",
        backend_validation={
            "enabled": True,
            "connections": [
                {
                    "id": "primary-rest",
                    "name": "Production REST API",
                    "type": "rest",
                    "base_url": "https://api.example.test",
                    "authentication": {"type": "bearer", "token": "secret-token"},
                },
                {
                    "id": "postgres-prod",
                    "name": "Production PostgreSQL",
                    "type": "sql",
                    "driver": "postgresql",
                    "connection_string": "postgresql://user:pass@db/app",
                },
            ],
        },
    )

    response = AgentConnectionResponse.from_connection(connection)

    assert response.backend_validation["connections"][0]["authentication"]["token"] == "******"
    assert response.backend_validation["connections"][1]["connection_string"] == "******"


def test_backend_validation_connection_catalog_is_attached_to_scenario():
    connection = AgentConnection(
        id="conn_1",
        name="Agent",
        type="chatbot",
        adapter="rest",
        backend_validation={
            "enabled": True,
            "connections": [{"id": "primary-rest", "name": "Production REST API", "type": "rest"}],
        },
    )

    scenario = _merge_backend_validation_into_scenario(_scenario(), connection)

    assert scenario.backend_validation[0]["backend"] == "primary-rest"
    assert scenario.agent.config["backend_validation_connections"]["connections"][0]["id"] == "primary-rest"


def test_masked_backend_validation_patch_preserves_existing_secrets():
    existing = {
        "enabled": True,
        "connections": [
            {
                "id": "primary-rest",
                "type": "rest",
                "authentication": {"type": "bearer", "token": "real-token"},
            },
            {
                "id": "postgres-prod",
                "type": "sql",
                "connection_string": "postgresql://user:pass@db/app",
            },
        ],
    }
    incoming = {
        "enabled": True,
        "connections": [
            {
                "id": "primary-rest",
                "type": "rest",
                "authentication": {"type": "bearer", "token": "******"},
            },
            {
                "id": "postgres-prod",
                "type": "sql",
                "connection_string": "******",
            },
        ],
    }

    merged = _merge_backend_validation_patch(existing, incoming)

    assert merged["connections"][0]["authentication"]["token"] == "real-token"
    assert merged["connections"][1]["connection_string"] == "postgresql://user:pass@db/app"
