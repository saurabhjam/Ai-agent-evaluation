from __future__ import annotations

from app.config import settings
from app.evaluation_service import EvaluationService
from app.evaluation_store import get_evaluation_report, save_evaluation_report
from app.executor import ExecutionResult
from app.report_engine import EvaluationReportEngine
from app.schemas import AgentConfig, Persona, TestScenario


class _DeterministicMetric:
    def __init__(self, name: str, scores: list[float], reasons: list[str]):
        self.name = name
        self._scores = iter(scores)
        self._reasons = iter(reasons)
        self.score = 0.0
        self.reason = ""

    def measure(self, _test_case) -> None:
        self.score = next(self._scores)
        self.reason = next(self._reasons)


class _NoBackendValidation:
    def validate(self, _transcript, _scenario):
        return None


def test_synthetic_evaluation_persistence_and_report_exports(monkeypatch, tmp_path):
    import app.evaluator as evaluator

    metrics = [
        _DeterministicMetric("Goal Completion", [0.8], ["The original goal was completed."]),
        _DeterministicMetric(
            "Answer Relevancy",
            [0.9, 0.5],
            ["The first answer was relevant.", "The second answer missed the request."],
        ),
        _DeterministicMetric("Hallucination", [1.0], ["No contradiction was established."]),
    ]
    monkeypatch.setattr(evaluator, "_build_metrics", lambda _persona, _rag_context: metrics)
    monkeypatch.setattr("app.evaluation_service.run_workflow_metrics", lambda _transcript: [])
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "phase2-evaluation.db"))

    transcript = [
        {"role": "simulated_user", "content": "Please check order 42.", "message_id": "u-1"},
        {"role": "agent", "content": "Order 42 is processing.", "message_id": "a-1"},
        {"role": "simulated_user", "content": "When will it ship?", "message_id": "u-2"},
        {"role": "agent", "content": "I cannot determine that here.", "message_id": "a-2"},
    ]
    scenario = TestScenario(
        scenario_id="provider_neutral_phase2",
        agent=AgentConfig(channel="chatbot", adapter="fake"),
        persona=Persona(
            name="Test Customer",
            goal="Check order 42 and obtain its current status.",
            tone="polite",
        ),
        max_turns=4,
        pass_threshold=0.7,
    )
    result = EvaluationService(backend_validation_engine=_NoBackendValidation()).evaluate(
        ExecutionResult(
            success=True,
            connection_id="synthetic-connection",
            agent_type="chatbot",
            adapter="fake",
            transcript=transcript,
            started_at="2026-10-19T10:00:00Z",
            completed_at="2026-10-19T10:01:00Z",
        ),
        scenario,
    )

    assert result.success is True
    by_name = {metric.name: metric for metric in result.metrics}
    assert by_name["Goal Completion"].score == 0.8
    assert by_name["Answer Relevancy"].score == 0.7
    assert by_name["Answer Relevancy"].conversation_message_id == "a-2"
    assert by_name["Hallucination"].evaluation_status == "not_evaluated"
    assert by_name["Hallucination"].evidence_status == "unverified"
    assert result.overall_score == 0.75
    assert result.passed is True

    payload = result.model_dump(mode="json")
    payload["evaluation_id"] = "eval-phase2-synthetic"
    saved = save_evaluation_report(payload)
    restored = get_evaluation_report(saved["evaluation_id"])
    assert restored is not None
    assert restored["overall_score"] == result.overall_score
    assert restored["metrics"] == payload["metrics"]

    reports = EvaluationReportEngine()
    html = reports.html(restored)
    pdf = reports.pdf(restored)
    docx = reports.docx(restored)
    assert "NOT EVALUATED" in html
    assert "75" in html
    assert pdf.startswith(b"%PDF")
    assert docx.startswith(b"PK")
