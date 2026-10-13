"""
Universal workflow engine for executing InteractionPlan objects.

This engine orchestrates state, retries, waiting, and completion. Interaction
execution is delegated to the injected InteractionExecutor; this module does
not implement browser automation, provider APIs, DOM parsing, uploads, or form
filling.
"""

from __future__ import annotations

import time

from app.interactive.interaction_plan import InteractionPlan, PlanStatus
from app.interactive.workflow_context import WorkflowContext
from app.interactive.workflow_models import Workflow
from app.interactive.workflow_result import WorkflowResult
from app.interactive.workflow_state import WorkflowStatus


class DefaultWorkflowEngine:
    name = "default"

    def run(self, plan: InteractionPlan, context: WorkflowContext) -> WorkflowResult:
        workflow = Workflow(metadata={"plan_id": plan.id, **context.metadata})
        workflow.mark_started()
        start = time.perf_counter()
        completed = []
        failed = []

        if plan.status == PlanStatus.failed:
            workflow.mark_failed()
            return WorkflowResult(
                success=False,
                status=workflow.status,
                duration=time.perf_counter() - start,
                metadata=workflow.metadata,
                error="Cannot execute a failed interaction plan.",
            )

        if not plan.ordered_interactions:
            workflow.mark_completed()
            return WorkflowResult(
                success=True,
                status=workflow.status,
                duration=time.perf_counter() - start,
                metadata={**workflow.metadata, "completed_steps": 0},
            )

        for index, interaction in enumerate(plan.ordered_interactions):
            workflow.current_step = index
            workflow.status = WorkflowStatus.ready

            if self._timed_out(start, context.timeout_seconds):
                workflow.failed_steps.append(interaction.id)
                failed.append(interaction)
                workflow.mark_failed()
                return WorkflowResult(
                    success=False,
                    status=workflow.status,
                    completed_interactions=completed,
                    failed_interactions=failed,
                    duration=time.perf_counter() - start,
                    metadata=self._metadata(workflow),
                    error="Workflow timed out.",
                )

            result = self._execute_with_retries(interaction, workflow, context)
            if not result.success:
                workflow.failed_steps.append(interaction.id)
                failed.append(interaction)
                workflow.mark_failed()
                return WorkflowResult(
                    success=False,
                    status=workflow.status,
                    completed_interactions=completed,
                    failed_interactions=failed,
                    duration=time.perf_counter() - start,
                    metadata=self._metadata(workflow),
                    error=result.error or result.message,
                )

            workflow.completed_steps.append(interaction.id)
            completed.append(interaction)
            workflow.status = WorkflowStatus.waiting_response
            if context.wait_after_step_seconds:
                time.sleep(context.wait_after_step_seconds)
            workflow.status = WorkflowStatus.validating

        workflow.mark_completed()
        return WorkflowResult(
            success=True,
            status=workflow.status,
            completed_interactions=completed,
            failed_interactions=failed,
            duration=time.perf_counter() - start,
            metadata=self._metadata(workflow),
        )

    def request_replan(self, workflow: Workflow, *, reason: str = "") -> None:
        workflow.status = WorkflowStatus.replanning
        workflow.metadata["replan_requested"] = True
        if reason:
            workflow.metadata["replan_reason"] = reason

    def cancel(self, workflow: Workflow, *, reason: str = "") -> None:
        workflow.status = WorkflowStatus.cancelled
        workflow.end_time = workflow.end_time or workflow.start_time
        if reason:
            workflow.metadata["cancel_reason"] = reason

    def _execute_with_retries(self, interaction, workflow: Workflow, context: WorkflowContext):
        attempts = context.max_retries + 1
        last_result = None
        for attempt in range(1, attempts + 1):
            workflow.status = WorkflowStatus.executing
            last_result = context.interaction_executor.execute(interaction, context.interaction_context)
            if last_result.success:
                return last_result
            if attempt < attempts:
                workflow.status = WorkflowStatus.retrying
                workflow.retry_count += 1
        return last_result

    def _timed_out(self, start: float, timeout_seconds: float | None) -> bool:
        return timeout_seconds is not None and (time.perf_counter() - start) > timeout_seconds

    def _metadata(self, workflow: Workflow) -> dict:
        return {
            **workflow.metadata,
            "current_step": workflow.current_step,
            "completed_steps": list(workflow.completed_steps),
            "failed_steps": list(workflow.failed_steps),
            "retry_count": workflow.retry_count,
        }
