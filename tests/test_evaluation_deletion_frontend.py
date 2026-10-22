from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "frontend" / "static" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "static" / "styles.css").read_text(encoding="utf-8")


def test_evaluation_history_exposes_delete_action_and_confirmation_modal():
    assert "management-delete-evaluation" in APP_JS
    assert 'id="modal-delete-evaluation"' in INDEX
    assert "This action cannot be undone" in INDEX
    assert "Delete Evaluation" in INDEX
    assert "btn-danger" in CSS


def test_delete_request_is_locked_and_uses_the_evaluation_delete_api():
    assert 'deleteEvaluation:        (id)     => API.delete("/evaluations/"' in APP_JS
    assert "if (!evaluation || !evaluation.evaluation_id || State.evaluationDeleteRunning) return;" in APP_JS
    assert "State.evaluationDeleteRunning = true" in APP_JS
    assert "button.disabled = true" in APP_JS
    assert "await API.deleteEvaluation(evaluation.evaluation_id)" in APP_JS
    assert "State.evaluationDeleteRunning = false" in APP_JS


def test_success_refreshes_agent_aggregates_and_failure_stays_visible():
    assert "await App.loadManagementAgentDetails(State.managementAgentDetail)" in APP_JS
    assert 'toast("Evaluation deleted successfully.", "success")' in APP_JS
    assert 'setAlert("modal-delete-evaluation-alert", "Delete failed: " + e.message, "error")' in APP_JS


def test_error_runs_display_na_instead_of_a_numeric_score():
    assert 'String(item.status || "").toLowerCase() === "error"' in APP_JS
    assert '? "N/A"' in APP_JS
