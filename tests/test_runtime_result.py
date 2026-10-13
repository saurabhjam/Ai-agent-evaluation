from app.interactive.interaction_models import Interaction
from app.interactive.interaction_types import InteractionType
from app.interactive.runtime_result import RuntimeResult
from app.interactive.workflow_state import WorkflowStatus


def test_runtime_result_normalizes_status_duration_and_count():
    result = RuntimeResult(
        success=True,
        workflow_status="COMPLETED",
        completed_interactions=[Interaction(type=InteractionType.text, label="Message")],
        duration=-1,
    )

    assert result.workflow_status == WorkflowStatus.completed
    assert result.duration == 0.0
    assert result.interaction_count == 1
