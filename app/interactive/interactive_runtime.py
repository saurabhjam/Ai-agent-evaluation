"""
Optional provider-neutral interactive chatbot runtime.

This runtime connects the Phase 1-5 architecture end-to-end. It only
orchestrates component detection, form understanding, planning, workflow
execution, and result aggregation. It does not implement browser automation,
DOM logic, uploads, form submission, or provider-specific behavior.
"""

from __future__ import annotations

import time

from app.interactive.component_detector import ComponentDetector
from app.interactive.form_context import FormContext
from app.interactive.form_engine import DefaultFormEngine
from app.interactive.interaction_context import InteractionContext
from app.interactive.interaction_executor import InteractionExecutor
from app.interactive.planning_context import PlanningContext
from app.interactive.decision_planner import DefaultDecisionPlanner
from app.interactive.runtime_context import RuntimeContext
from app.interactive.runtime_result import RuntimeResult
from app.interactive.workflow_context import WorkflowContext
from app.interactive.workflow_engine import DefaultWorkflowEngine
from app.interactive.workflow_state import WorkflowStatus


class InteractiveRuntime:
    name = "default"

    def __init__(
        self,
        *,
        component_detector: ComponentDetector | None = None,
        form_engine: DefaultFormEngine | None = None,
        decision_planner: DefaultDecisionPlanner | None = None,
        interaction_executor: InteractionExecutor | None = None,
        workflow_engine: DefaultWorkflowEngine | None = None,
    ) -> None:
        self.component_detector = component_detector or ComponentDetector()
        self.form_engine = form_engine or DefaultFormEngine()
        self.decision_planner = decision_planner or DefaultDecisionPlanner()
        self.interaction_executor = interaction_executor or InteractionExecutor()
        self.workflow_engine = workflow_engine or DefaultWorkflowEngine()

    def run(self, context: RuntimeContext) -> RuntimeResult:
        start = time.perf_counter()
        detected_components = []
        detected_forms = []
        try:
            component_result = self.component_detector.detect(
                context.provider_response,
                provider=context.provider,
                metadata=context.metadata,
            )
            detected_components = component_result.components
            if not component_result.success:
                return RuntimeResult(
                    success=False,
                    workflow_status=WorkflowStatus.failed,
                    detected_components=detected_components,
                    duration=time.perf_counter() - start,
                    metadata={"stage": "component_detection", **context.metadata},
                    error=component_result.error,
                )

            form_result = self.form_engine.understand(
                FormContext(
                    components=detected_components,
                    variables=context.variables,
                    scenario=context.scenario,
                    conversation_state=context.conversation_state,
                    metadata=context.metadata,
                )
            )
            detected_forms = form_result.forms
            if not form_result.success:
                return RuntimeResult(
                    success=False,
                    workflow_status=WorkflowStatus.failed,
                    detected_components=detected_components,
                    detected_forms=detected_forms,
                    duration=time.perf_counter() - start,
                    metadata={"stage": "form_engine", **context.metadata},
                    error=form_result.error,
                )

            plan = self.decision_planner.plan(
                PlanningContext(
                    scenario=context.scenario,
                    components=detected_components,
                    conversation_state=context.conversation_state,
                    variables=context.variables,
                    current_step=context.current_step,
                    previous_result=context.previous_result,
                    metadata={**context.metadata, "form_count": len(detected_forms)},
                )
            )

            workflow_result = self.workflow_engine.run(
                plan,
                WorkflowContext(
                    interaction_context=InteractionContext(
                        adapter=context.adapter,
                        scenario_id=getattr(context.scenario, "scenario_id", None),
                        metadata=context.metadata,
                    ),
                    interaction_executor=self.interaction_executor,
                    metadata={"runtime": self.name, **context.metadata},
                ),
            )

            return RuntimeResult(
                success=workflow_result.success,
                workflow_status=workflow_result.status,
                interaction_count=len(plan.ordered_interactions),
                completed_interactions=workflow_result.completed_interactions,
                failed_interactions=workflow_result.failed_interactions,
                detected_components=detected_components,
                detected_forms=detected_forms,
                duration=time.perf_counter() - start,
                metadata={
                    **workflow_result.metadata,
                    "component_count": len(detected_components),
                    "form_count": len(detected_forms),
                    "plan_id": plan.id,
                },
                error=workflow_result.error,
            )
        except Exception as exc:
            return RuntimeResult(
                success=False,
                workflow_status=WorkflowStatus.failed,
                detected_components=detected_components,
                detected_forms=detected_forms,
                duration=time.perf_counter() - start,
                metadata={"stage": "runtime", **context.metadata},
                error=f"{type(exc).__name__}: {exc}",
            )


def chatbot_execution_mode() -> str:
    from app.config import settings

    mode = (settings.chatbot_execution_mode or "legacy").strip().lower()
    return mode if mode in {"legacy", "interactive"} else "legacy"


def interactive_runtime_enabled() -> bool:
    return chatbot_execution_mode() == "interactive"
