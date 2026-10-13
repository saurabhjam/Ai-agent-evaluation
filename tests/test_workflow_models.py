import pytest

from app.interactive.workflow_context import WorkflowContext
from app.interactive.workflow_models import Workflow
from app.interactive.workflow_result import WorkflowResult
from app.interactive.workflow_state import WorkflowStatus


def test_workflow_model_tracks_lifecycle():
    workflow = Workflow(id="wf-1")

    workflow.mark_started()
    assert workflow.status == WorkflowStatus.started
    assert workflow.start_time is not None

    workflow.mark_completed()
    assert workflow.status == WorkflowStatus.completed
    assert workflow.end_time is not None


def test_workflow_rejects_invalid_counts():
    with pytest.raises(ValueError, match="current_step"):
        Workflow(current_step=-1)

    with pytest.raises(ValueError, match="retry_count"):
        Workflow(retry_count=-1)


def test_workflow_context_validates_retry_and_timeout():
    with pytest.raises(ValueError, match="max_retries"):
        WorkflowContext(interaction_context=None, interaction_executor=None, max_retries=-1)

    with pytest.raises(ValueError, match="timeout"):
        WorkflowContext(interaction_context=None, interaction_executor=None, timeout_seconds=-1)


def test_workflow_result_normalizes_status_and_duration():
    result = WorkflowResult(success=True, status="COMPLETED", duration=-1)

    assert result.status == WorkflowStatus.completed
    assert result.duration == 0.0
