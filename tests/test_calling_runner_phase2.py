from __future__ import annotations

from app.calling.models import CallDirection, CallStatus
from app.calling.providers.mock import MockCallProvider
from app.calling.runner import CallSessionRunner, build_mock_transcript


def test_call_session_runner_produces_normalized_conversation():
    runner = CallSessionRunner(provider_adapter=MockCallProvider())

    result = runner.run_mock_call(
        scenario_id="appointment-call",
        retrieval_context=["Appointments can be booked for tomorrow morning."],
    )

    execution = result.execution_result
    normalized = result.normalized_conversation

    assert execution.success is True
    assert execution.session.status == CallStatus.completed
    assert execution.transcript is not None
    assert len(execution.events) == 6
    assert normalized.channel == "calling"
    assert normalized.metadata["scenario_id"] == "appointment-call"
    assert normalized.retrieval_context == ["Appointments can be booked for tomorrow morning."]
    assert [message.role for message in normalized.messages] == [
        "simulated_user",
        "agent",
        "simulated_user",
        "agent",
    ]
    assert normalized.messages[0].content == "Hello, I'd like to book an appointment."


def test_call_session_runner_supports_inbound_simulation():
    runner = CallSessionRunner(provider_adapter=MockCallProvider())

    result = runner.run_mock_call(direction=CallDirection.inbound, from_="+15550000003")

    assert result.execution_result.session.direction == CallDirection.inbound
    assert result.execution_result.session.status == CallStatus.completed
    assert result.normalized_conversation.channel == "calling"


def test_build_mock_transcript_uses_session_identifiers():
    provider = MockCallProvider()
    session = provider.start_outbound_call(to="+15550000002")

    transcript = build_mock_transcript(session)

    assert transcript.session_id == session.session_id
    assert transcript.run_id == session.run_id
    assert transcript.source == "mock_provider"
    assert transcript.metadata["provider_call_id"] == session.provider_call_id
