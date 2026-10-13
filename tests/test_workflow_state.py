from app.interactive.workflow_engine import DefaultWorkflowEngine
from app.interactive.workflow_models import Workflow
from app.interactive.workflow_state import WorkflowStatus


def test_request_replan_updates_workflow_state():
    workflow = Workflow(id="wf")

    DefaultWorkflowEngine().request_replan(workflow, reason="new components detected")

    assert workflow.status == WorkflowStatus.replanning
    assert workflow.metadata["replan_requested"] is True
    assert workflow.metadata["replan_reason"] == "new components detected"


def test_cancel_updates_workflow_state():
    workflow = Workflow(id="wf")

    DefaultWorkflowEngine().cancel(workflow, reason="user stopped")

    assert workflow.status == WorkflowStatus.cancelled
    assert workflow.metadata["cancel_reason"] == "user stopped"
