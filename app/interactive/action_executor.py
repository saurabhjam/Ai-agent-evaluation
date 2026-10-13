"""
Safe action execution helpers.

Phase 2 remains isolated: this executor is not imported by runtime execution.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.interactive.action_validator import ActionValidator
from app.interactive.adapter_action import AdapterCapabilityResolver
from app.interactive.models import ActionType, UserAction
from app.interactive.planner import ActionProposal


@dataclass
class ActionExecutionResult:
    success: bool
    action: UserAction
    executed_as: ActionType
    message: str = ""
    fallback_used: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class ActionExecutor:
    """Validate and execute proposed user actions through an adapter surface."""

    def __init__(
        self,
        validator: ActionValidator | None = None,
        capability_resolver: AdapterCapabilityResolver | None = None,
    ) -> None:
        self.validator = validator or ActionValidator()
        self.capability_resolver = capability_resolver or AdapterCapabilityResolver()

    def execute(
        self,
        *,
        proposal: ActionProposal,
        adapter: Any,
        adapter_name: str,
        agent_prompt: str | None = None,
    ) -> ActionExecutionResult:
        validation = self.validator.validate(proposal.action, adapter_name=adapter_name)
        action = validation.normalized_action or proposal.action
        fallback_used = not validation.valid

        if not validation.valid:
            fallback_validation = self.validator.validate(action, adapter_name=adapter_name)
            if not fallback_validation.valid:
                return ActionExecutionResult(
                    success=False,
                    action=action,
                    executed_as=action.type,
                    message=f"Action validation failed: {validation.reason}; fallback failed: {fallback_validation.reason}",
                    fallback_used=True,
                )
            action = fallback_validation.normalized_action or action

        try:
            self._execute_action(
                action=action,
                adapter=adapter,
                adapter_name=adapter_name,
                agent_prompt=agent_prompt,
            )
        except Exception as exc:
            fallback = self._fallback_send_text(action)
            if fallback.type == action.type:
                return ActionExecutionResult(
                    success=False,
                    action=action,
                    executed_as=action.type,
                    message=f"Action execution failed: {type(exc).__name__}: {exc}",
                    fallback_used=fallback_used,
                )
            self._execute_action(
                action=fallback,
                adapter=adapter,
                adapter_name=adapter_name,
                agent_prompt=agent_prompt,
            )
            return ActionExecutionResult(
                success=True,
                action=fallback,
                executed_as=fallback.type,
                message=f"Used SEND_TEXT fallback after {action.type.value} failed.",
                fallback_used=True,
                metadata={"original_action": action.type.value},
            )

        return ActionExecutionResult(
            success=True,
            action=action,
            executed_as=action.type,
            message="Action executed.",
            fallback_used=fallback_used,
        )

    def _execute_action(
        self,
        *,
        action: UserAction,
        adapter: Any,
        adapter_name: str,
        agent_prompt: str | None,
    ) -> None:
        if self.capability_resolver.supports_native_action(
            adapter,
            action.type,
            adapter_name=adapter_name,
        ):
            self.capability_resolver.execute_native(adapter, action)
            return

        if action.type == ActionType.send_text:
            self._send_message(adapter, action.text or "", agent_prompt=agent_prompt)
            return

        if action.type in {ActionType.click_option, ActionType.click_button, ActionType.select_dropdown}:
            self._send_message(adapter, action.value or action.target or "", agent_prompt=agent_prompt)
            return

        if action.type in {ActionType.confirm, ActionType.cancel}:
            self._send_message(adapter, action.value or action.target or action.type.value.title(), agent_prompt=agent_prompt)
            return

        if action.type in {ActionType.upload_file, ActionType.upload_document}:
            if hasattr(adapter, "upload_file"):
                adapter.upload_file(action.file)
                return
            raise NotImplementedError("Adapter does not support file upload.")

        if action.type in {ActionType.select_date, ActionType.select_time}:
            self._send_message(adapter, action.value or "", agent_prompt=agent_prompt)
            return

        if action.type == ActionType.wait:
            delay = self._wait_seconds(action)
            time.sleep(delay)
            return

        raise NotImplementedError(f"Action '{action.type.value}' is not executable by the generic executor.")

    def _send_message(self, adapter: Any, message: str, *, agent_prompt: str | None) -> None:
        if not hasattr(adapter, "send_message"):
            raise NotImplementedError("Adapter does not expose send_message.")
        adapter.send_message(message, agent_prompt=agent_prompt, attachments=None)

    def _fallback_send_text(self, action: UserAction) -> UserAction:
        text = action.text or action.value or action.target
        if not text:
            return action
        return UserAction(type=ActionType.send_text, text=text)

    def _wait_seconds(self, action: UserAction) -> float:
        raw = action.value or action.metadata.get("seconds") or 1
        try:
            return max(0.0, min(30.0, float(raw)))
        except (TypeError, ValueError):
            return 1.0
