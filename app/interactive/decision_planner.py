"""
Universal decision planner for chatbot components.

The planner converts detected components into an ordered InteractionPlan. It
does not execute the plan and contains no provider-specific logic.
"""

from __future__ import annotations

import re
from typing import Any

from app.interactive.component_models import Component
from app.interactive.component_types import ComponentType
from app.interactive.interaction_models import Interaction
from app.interactive.interaction_plan import InteractionPlan, PlanStatus
from app.interactive.interaction_types import InteractionType
from app.interactive.planning_context import PlanningContext
from app.interactive.planning_result import PlanningResult


class DefaultDecisionPlanner:
    name = "default"

    def plan(self, context: PlanningContext) -> InteractionPlan:
        interactions: list[Interaction] = []
        for component in context.components:
            interaction = self._interaction_for_component(component, context.variables)
            if interaction is not None:
                interactions.append(interaction)

        if not interactions:
            return InteractionPlan(
                ordered_interactions=[],
                reason="No actionable components were detected.",
                confidence=0.0,
                status=PlanStatus.empty,
                metadata={"planner": self.name},
                next_expected_state=context.current_step,
            )

        return InteractionPlan(
            ordered_interactions=interactions,
            reason="Mapped detected chatbot components to provider-neutral interactions.",
            confidence=self._confidence(interactions),
            status=PlanStatus.planned,
            metadata={"planner": self.name, "component_count": len(context.components)},
            next_expected_state="interaction_execution",
        )

    def plan_result(self, context: PlanningContext) -> PlanningResult:
        try:
            plan = self.plan(context)
            return PlanningResult(success=plan.status != PlanStatus.failed, plan=plan, reason=plan.reason)
        except Exception as exc:
            return PlanningResult(success=False, error=f"{type(exc).__name__}: {exc}")

    def _interaction_for_component(
        self,
        component: Component,
        variables: dict[str, Any],
    ) -> Interaction | None:
        mapping = {
            ComponentType.text: None,
            ComponentType.markdown: None,
            ComponentType.html: None,
            ComponentType.image: None,
            ComponentType.document: None,
            ComponentType.card: None,
            ComponentType.carousel: None,
            ComponentType.list: None,
            ComponentType.table: None,
            ComponentType.button: InteractionType.button,
            ComponentType.quick_reply: InteractionType.quick_reply,
            ComponentType.dropdown: InteractionType.dropdown,
            ComponentType.checkbox: InteractionType.checkbox,
            ComponentType.radio_button: InteractionType.radio_button,
            ComponentType.date_picker: InteractionType.date_picker,
            ComponentType.time_picker: InteractionType.time_picker,
            ComponentType.email_input: InteractionType.email_input,
            ComponentType.phone_input: InteractionType.phone_input,
            ComponentType.number_input: InteractionType.number_input,
            ComponentType.otp_input: InteractionType.otp_input,
            ComponentType.search_box: InteractionType.search_box,
            ComponentType.text_area: InteractionType.text,
            ComponentType.upload: InteractionType.upload_file,
            ComponentType.link: InteractionType.custom_action,
            ComponentType.unknown: InteractionType.custom_action,
        }
        interaction_type = mapping.get(component.type)
        if interaction_type is None or not component.enabled or not component.visible:
            return None

        value = self._value_for_component(component, variables)
        return Interaction(
            type=interaction_type,
            label=component.label,
            selector=component.selector,
            value=value,
            required=component.required,
            metadata={
                "component_id": component.id,
                "component_type": component.type.value,
            },
            provider_metadata=component.provider_metadata,
        )

    def _value_for_component(self, component: Component, variables: dict[str, Any]) -> Any:
        variable_value = self._variable_match(component, variables)
        if variable_value is not None:
            return variable_value
        if component.value is not None:
            return component.value
        if component.has_options:
            return component.options[0].option_value()
        return component.text or component.label

    def _variable_match(self, component: Component, variables: dict[str, Any]) -> Any:
        candidates = {
            self._normalize_key(component.label),
            self._normalize_key(component.id),
            self._normalize_key(component.text or ""),
        }
        for key, value in variables.items():
            if self._normalize_key(str(key)) in candidates:
                return value
        return None

    def _normalize_key(self, value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
        return normalized.strip("_")

    def _confidence(self, interactions: list[Interaction]) -> float:
        if not interactions:
            return 0.0
        required_count = sum(1 for item in interactions if item.required)
        base = 0.72
        if required_count:
            base += 0.08
        return min(0.9, base)
