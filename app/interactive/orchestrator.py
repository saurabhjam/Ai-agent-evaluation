"""
Conversation Orchestrator for User Action Engine runtime integration.

This module owns per-turn decisions when the feature flag is enabled. It keeps
ScenarioExecutor thin and preserves the existing text path whenever no
interactive content is detected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.interactive.action_executor import ActionExecutionResult, ActionExecutor
from app.interactive.conversation_state import ConversationStateBuilder
from app.interactive.planner import ActionProposal, UserActionEngine
from app.interactive.response_understanding import ResponseUnderstanding


END_TOKEN = "[END_CONVERSATION]"


@dataclass
class ConversationTurnResult:
    should_continue: bool
    used_interactive_path: bool = False
    user_message: str | None = None
    action_proposal: ActionProposal | None = None
    execution_result: ActionExecutionResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ConversationOrchestrator:
    """
    Coordinates one chatbot conversation turn.

    If no interactive content is found, this deliberately executes the same
    text-generation/send_message behavior that ScenarioExecutor used before
    Phase 3.
    """

    def __init__(
        self,
        *,
        response_understanding: ResponseUnderstanding | None = None,
        state_builder: ConversationStateBuilder | None = None,
        user_action_engine: UserActionEngine | None = None,
        action_executor: ActionExecutor | None = None,
        text_turn_generator: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.response_understanding = response_understanding or ResponseUnderstanding()
        self.state_builder = state_builder or ConversationStateBuilder()
        self.user_action_engine = user_action_engine or UserActionEngine()
        self.action_executor = action_executor or ActionExecutor()
        self.text_turn_generator = text_turn_generator

    def run_turn(
        self,
        *,
        adapter: Any,
        adapter_name: str,
        scenario: Any,
        agent_prompt: str | None = None,
    ) -> ConversationTurnResult:
        transcript = adapter.get_transcript()
        latest_agent_text = self._latest_agent_text(transcript)
        metadata = self._latest_response_metadata(adapter)
        normalized = self.response_understanding.normalize(
            text=latest_agent_text,
            metadata=metadata,
            raw=metadata,
        )

        if not normalized.has_interactive_content:
            return self._run_existing_text_turn(
                adapter=adapter,
                scenario=scenario,
                transcript=transcript,
                agent_prompt=agent_prompt,
            )

        state = self.state_builder.build(
            scenario_id=getattr(scenario, "scenario_id", None),
            persona_goal=getattr(getattr(scenario, "persona", None), "goal", ""),
            transcript=transcript,
            current_agent_response=normalized,
        )
        proposal = self.user_action_engine.propose_action(
            state=state,
            adapter_name=adapter_name,
            scenario=scenario,
            persona=getattr(scenario, "persona", None),
            transcript=transcript,
            observation=normalized,
        )
        execution = self.action_executor.execute(
            proposal=proposal,
            adapter=adapter,
            adapter_name=adapter_name,
            agent_prompt=agent_prompt,
        )
        return ConversationTurnResult(
            should_continue=execution.success,
            used_interactive_path=True,
            action_proposal=proposal,
            execution_result=execution,
            metadata={
                "interactive_count": len(normalized.interactive),
                "agent_response_text": latest_agent_text,
            },
        )

    def _run_existing_text_turn(
        self,
        *,
        adapter: Any,
        scenario: Any,
        transcript: list[Any],
        agent_prompt: str | None,
    ) -> ConversationTurnResult:
        generator = self._text_turn_generator()
        user_turn = generator(
            scenario.persona,
            transcript,
        )
        user_message = user_turn["message"]
        user_attachments = user_turn.get("attachments")

        if END_TOKEN in user_message or not user_message:
            return ConversationTurnResult(should_continue=False, user_message=user_message)

        adapter.send_message(
            user_message,
            agent_prompt=agent_prompt,
            attachments=user_attachments,
        )
        return ConversationTurnResult(should_continue=True, user_message=user_message)

    def _text_turn_generator(self) -> Callable[..., dict[str, Any]]:
        if self.text_turn_generator is not None:
            return self.text_turn_generator
        from app.simulator import generate_next_user_turn

        return generate_next_user_turn

    def _latest_agent_text(self, transcript: list[Any]) -> str:
        for turn in reversed(transcript or []):
            role = getattr(turn, "role", None)
            if role == "agent":
                return str(getattr(turn, "content", "") or "")
            if isinstance(turn, dict) and turn.get("role") == "agent":
                return str(turn.get("content") or "")
        return ""

    def _latest_response_metadata(self, adapter: Any) -> dict[str, Any]:
        if hasattr(adapter, "get_last_response_metadata"):
            metadata = adapter.get_last_response_metadata()
            return metadata if isinstance(metadata, dict) else {}
        return {}
