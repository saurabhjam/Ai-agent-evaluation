from __future__ import annotations

from app.calling.config import CallingProviderConfig
from app.calling.conversation_evidence import EvidenceArtifact
from app.calling.execution_context import CallingExecutionContext
from app.schemas import AgentConfig, Persona, TestScenario


def _scenario() -> TestScenario:
    return TestScenario(
        scenario_id="calling-context",
        agent=AgentConfig(channel="calling", adapter="mock"),
        persona=Persona(
            name="Ava",
            goal="Book an appointment for tomorrow morning",
            tone="polite",
        ),
        rag_context=["Appointments can be booked for tomorrow."],
    )


def test_execution_context_contains_required_runtime_fields():
    artifact = EvidenceArtifact(
        session_id="session-1",
        name="logs.json",
        artifact_type="logs",
    )
    context = CallingExecutionContext(
        scenario=_scenario(),
        provider_config=CallingProviderConfig(provider_name="mock"),
        metadata={"source": "unit-test"},
        artifacts=[artifact],
        provider="mock",
    )

    assert context.scenario.scenario_id == "calling-context"
    assert context.provider_config.provider_name == "mock"
    assert context.session_id
    assert context.run_id
    assert context.created_at
    assert context.metadata == {"source": "unit-test"}
    assert context.artifacts == [artifact]
    assert context.provider == "mock"


def test_execution_context_start_and_end_are_copy_updates():
    context = CallingExecutionContext(scenario=_scenario())

    started = context.mark_started("2026-10-01T10:00:00+00:00")
    ended = started.mark_ended("2026-10-01T10:01:00+00:00")

    assert context.started_at is None
    assert started.started_at == "2026-10-01T10:00:00+00:00"
    assert ended.ended_at == "2026-10-01T10:01:00+00:00"
