from dataclasses import dataclass

from app.interactive.orchestrator import ConversationOrchestrator


@dataclass
class FakePersona:
    goal: str


@dataclass
class FakeScenario:
    scenario_id: str
    persona: FakePersona
    agent_prompt: str | None = None


@dataclass
class FakeMessage:
    role: str
    content: str


class FakeAdapter:
    def __init__(self, transcript=None, metadata=None):
        self.transcript = transcript or []
        self.metadata = metadata or {}
        self.sent = []

    def get_transcript(self):
        return self.transcript

    def send_message(self, message, agent_prompt=None, attachments=None):
        self.sent.append((message, agent_prompt, attachments))

    def get_last_response_metadata(self):
        return self.metadata


def test_text_only_turn_uses_existing_text_generator():
    adapter = FakeAdapter()
    scenario = FakeScenario("s1", FakePersona("Report a maintenance issue"))

    orchestrator = ConversationOrchestrator(
        text_turn_generator=lambda persona, transcript: {"message": "I need help.", "attachments": None}
    )

    result = orchestrator.run_turn(
        adapter=adapter,
        adapter_name="rest",
        scenario=scenario,
        agent_prompt="prompt",
    )

    assert result.should_continue is True
    assert result.used_interactive_path is False
    assert adapter.sent == [("I need help.", "prompt", None)]


def test_interactive_turn_selects_option_and_skips_text_generator():
    transcript = [
        FakeMessage(
            role="agent",
            content="Choose one\n• Charlie Parker\n• Harris Park\n• Show results across my entire portfolio",
        )
    ]
    adapter = FakeAdapter(transcript=transcript)
    scenario = FakeScenario("s1", FakePersona("Report a maintenance issue across my entire portfolio"))

    def fail_generator(persona, transcript):
        raise AssertionError("Text generator should not run for interactive content")

    orchestrator = ConversationOrchestrator(text_turn_generator=fail_generator)
    result = orchestrator.run_turn(adapter=adapter, adapter_name="rest", scenario=scenario)

    assert result.should_continue is True
    assert result.used_interactive_path is True
    assert result.action_proposal.action.target == "Show results across my entire portfolio"
    assert adapter.sent == [("Show results across my entire portfolio", None, None)]


def test_validator_failure_falls_back_to_send_text_for_unsupported_action():
    transcript = [
        FakeMessage(role="agent", content="Upload damage photo.")
    ]
    adapter = FakeAdapter(transcript=transcript)
    scenario = FakeScenario("s1", FakePersona("Report a maintenance issue"))

    result = ConversationOrchestrator().run_turn(
        adapter=adapter,
        adapter_name="unknown_text_only",
        scenario=scenario,
    )

    assert result.should_continue is True
    assert result.used_interactive_path is True
    assert result.action_proposal.metadata["planner"] == "validator_fallback"
    assert result.execution_result.executed_as.value == "SEND_TEXT"
    assert adapter.sent == [("I need help continuing.", None, None)]


def test_end_conversation_from_text_generator_stops_loop():
    adapter = FakeAdapter()
    scenario = FakeScenario("s1", FakePersona("Goal is complete"))
    orchestrator = ConversationOrchestrator(
        text_turn_generator=lambda persona, transcript: {"message": "[END_CONVERSATION]"}
    )

    result = orchestrator.run_turn(adapter=adapter, adapter_name="rest", scenario=scenario)

    assert result.should_continue is False
    assert adapter.sent == []
