from __future__ import annotations

import json

import pytest

from app import evaluator
from app.benchmarks import judge_accuracy
from app.benchmarks.human_review import build_review_packets, validate_completed_reviews
from app.benchmarks.judge_accuracy import (
    BenchmarkRateLimitError,
    JudgeAccuracyBenchmark,
    _compare_case,
    _isolated_judge,
    _rate_limit_details,
    _summarize,
    compare_benchmark_artifacts,
)


def test_golden_dataset_is_large_diverse_and_honestly_labeled():
    benchmark = JudgeAccuracyBenchmark()
    assert len(benchmark.cases) >= 30
    assert not any(case["label_quality"] == "human_reviewed" for case in benchmark.cases)
    tags = {tag for case in benchmark.cases for tag in case.get("tags", [])}
    assert {"goal_failure", "topic_change", "no_contradiction", "context_loss", "persona_separation", "evidence_unavailable"} <= tags
    case_ids = {case["case_id"] for case in benchmark.cases}
    assert {"goal_success_banking", "insurance_intent", "travel_wrong_intent", "healthcare_clarification", "retail_complete_answer", "hospitality_incomplete"} <= case_ids


def test_provider_judges_do_not_cross_fallback(monkeypatch):
    judge = judge_accuracy.GroqOnlyBenchmarkJudge.__new__(judge_accuracy.GroqOnlyBenchmarkJudge)
    judge.model_name = "groq-test"

    class FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("groq failed")

    judge.client = type("Client", (), {"chat": type("Chat", (), {"completions": FailingCompletions()})()})()
    with pytest.raises(RuntimeError, match="groq failed"):
        judge.generate("return json")
    assert not hasattr(judge, "fallback")


def test_isolated_judge_filters_metrics_and_restores_production_state(monkeypatch):
    original_judge = object()
    monkeypatch.setattr(evaluator, "_judge", original_judge)

    class Metric:
        def __init__(self, name):
            self.name = name

    monkeypatch.setattr(evaluator, "_build_metrics", lambda *args: [Metric("Goal Completion"), Metric("Answer Relevancy")])
    installed_builder = evaluator._build_metrics
    selected_judge = object()
    with _isolated_judge(selected_judge, {"Goal Completion"}):
        metrics = evaluator._build_metrics(None, None)
        assert evaluator._judge is selected_judge
        assert [item.name for item in metrics] == ["Goal Completion"]
    assert evaluator._judge is original_judge
    assert evaluator._build_metrics is installed_builder


def test_compare_case_calculates_range_status_evidence_and_explanation():
    case = {
        "labels": {
            "Answer Relevancy": {
                "score_range": [0.7, 0.9], "status": "pass",
                "expected_evidence_message_ids": ["a-2"],
                "forbidden_reason_terms": ["contradiction"],
            }
        }
    }
    result = _compare_case(case, [{
        "name": "Answer Relevancy", "score": 0.8, "passed": True,
        "conversation_message_id": "a-2", "reason": "The answer is relevant.",
    }])[0]
    assert result["absolute_error_to_midpoint"] == 0.0
    assert result["within_range"] is True
    assert result["status_agreement"] is True
    assert result["evidence_reference_valid"] is True
    assert result["unsupported_explanation"] is False


def test_compare_case_converts_evaluated_status_to_pass_or_fail():
    case = {"labels": {"Hallucination": {"score_range": [0.0, 0.55], "status": "fail"}}}
    result = _compare_case(case, [{
        "name": "Hallucination", "score": 0.55, "passed": False,
        "evaluation_status": "evaluated", "reason": "Contradicted by evidence.",
    }])[0]
    assert result["actual_status"] == "fail"
    assert result["status_agreement"] is True


def test_summary_separates_accuracy_stability_latency_and_failures():
    cases = [{"case_id": "c1", "tags": ["no_contradiction"]}]
    runs = [
        {
            "provider": "groq", "case_id": "c1", "status": "success", "latency_ms": 100,
            "comparison": [{"metric": "Multi-turn Consistency", "status": "compared", "score": 0.8, "absolute_error_to_midpoint": 0.0, "within_range": True, "expected_status": "pass", "actual_status": "pass", "status_agreement": True, "evidence_reference_valid": True, "unsupported_explanation": False}],
            "metrics": [{"name": "Multi-turn Consistency", "score": 0.8, "diagnostics": {"judge_invocations": [{"token_usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}]}}],
        },
        {
            "provider": "groq", "case_id": "c1", "status": "error", "latency_ms": 20,
            "comparison": [], "metrics": [],
        },
    ]
    summary = _summarize(runs, cases)["groq"]
    assert summary["failure_rate"] == 0.5
    assert summary["pass_fail_agreement"] == 1.0
    assert summary["average_latency_ms"] == 100
    assert summary["token_usage"]["total_tokens"] == 12
    assert summary["estimated_cost"] is None


def test_runner_records_provider_failure_without_substitution(monkeypatch, tmp_path):
    benchmark = JudgeAccuracyBenchmark()
    benchmark.cases = benchmark.cases[:1]

    class FailedJudge:
        def get_model_name(self):
            return "failed-model"

    monkeypatch.setattr(judge_accuracy, "_make_judge", lambda provider: FailedJudge())
    monkeypatch.setattr(evaluator, "evaluate_transcript", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("provider timeout")))
    result = benchmark.run(["groq"], repeats=1)
    run = result["runs"][0]
    assert run["status"] == "error"
    assert run["provider"] == "groq"
    assert run["error"]["type"] == "TimeoutError"
    assert result["summary"]["groq"]["failure_rate"] == 1.0


def test_runner_treats_caught_metric_error_as_provider_failure(monkeypatch):
    from app.schemas import MetricResult

    benchmark = JudgeAccuracyBenchmark()
    benchmark.cases = benchmark.cases[:1]

    class Judge:
        def get_model_name(self):
            return "quota-limited-model"

    monkeypatch.setattr(judge_accuracy, "_make_judge", lambda provider: Judge())
    monkeypatch.setattr(evaluator, "evaluate_transcript", lambda *args, **kwargs: [
        MetricResult(
            name="Goal Completion", score=0.0, passed=False,
            reason="Metric failed to evaluate: ResourceExhausted",
            evaluation_status="error",
        )
    ])
    result = benchmark.run(["gemini"], repeats=1)
    assert result["runs"][0]["status"] == "error"
    assert result["runs"][0]["error"]["type"] == "JudgeMetricError"
    assert result["summary"]["gemini"]["failure_rate"] == 1.0


def test_benchmark_output_is_json_serializable(monkeypatch):
    benchmark = JudgeAccuracyBenchmark()
    benchmark.cases = benchmark.cases[:1]

    class Judge:
        def get_model_name(self):
            return "mock-model"

    monkeypatch.setattr(judge_accuracy, "_make_judge", lambda provider: Judge())
    monkeypatch.setattr(evaluator, "evaluate_transcript", lambda *args, **kwargs: [])
    result = benchmark.run(["gemini"], repeats=1)
    json.dumps(result)
    assert result["label_disclaimer"].startswith("Synthetic labels")


def test_rate_limit_classification_distinguishes_daily_and_minute_limits():
    daily = _rate_limit_details(RuntimeError(
        "Error code: 429 tokens per day (TPD). Please try again in 3m28.5s"
    ))
    minute = _rate_limit_details(RuntimeError(
        "Error code: 429 tokens per minute (TPM). Please try again in 2.5s"
    ))
    assert daily == {
        "status_code": 429, "limit_type": "tokens_per_day",
        "retry_after_seconds": 208.5, "quota_exhausted": True,
    }
    assert minute["limit_type"] == "tokens_per_minute"
    assert minute["retry_after_seconds"] == 2.5
    assert minute["quota_exhausted"] is False


def test_groq_judge_latches_daily_quota_without_second_api_request():
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError("Error code: 429 tokens per day (TPD). Please try again in 4m0s")

    judge = judge_accuracy.GroqOnlyBenchmarkJudge.__new__(judge_accuracy.GroqOnlyBenchmarkJudge)
    judge.model_name = "test-model"
    judge.client = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
    judge._quota_error = None

    with pytest.raises(BenchmarkRateLimitError):
        judge.generate("Return JSON")
    with pytest.raises(BenchmarkRateLimitError):
        judge.generate("Return JSON")
    assert len(calls) == 1


def test_daily_quota_stops_run_and_persists_checkpoint(monkeypatch, tmp_path):
    benchmark = JudgeAccuracyBenchmark()
    benchmark.cases = benchmark.cases[:2]
    monkeypatch.setattr(judge_accuracy, "_make_judge", lambda provider: object())
    calls = []

    def quota_failure(provider, judge, case, repeat):
        calls.append((case["case_id"], repeat))
        return {
            "provider": provider, "case_id": case["case_id"], "repeat": repeat,
            "status": "error", "error": {
                "type": "BenchmarkRateLimitError",
                "message": "daily exhausted",
                "rate_limit": {"limit_type": "tokens_per_day", "quota_exhausted": True},
            },
            "metrics": [], "comparison": [],
        }

    monkeypatch.setattr(benchmark, "_run_case", quota_failure)
    output = tmp_path / "checkpoint.json"
    result = benchmark.run(["groq"], repeats=3, output_path=output)

    assert len(calls) == 1
    assert result["run_state"]["complete"] is False
    assert result["run_state"]["stopped_reason"]["type"] == "quota_exhausted"
    assert json.loads(output.read_text())["run_state"]["recorded_runs"] == 1


def test_resume_skips_successful_keys_and_retries_failed_key(monkeypatch, tmp_path):
    benchmark = JudgeAccuracyBenchmark()
    benchmark.cases = benchmark.cases[:1]
    case_id = benchmark.cases[0]["case_id"]
    output = tmp_path / "resume.json"
    output.write_text(json.dumps({"runs": [
        {"provider": "groq", "case_id": case_id, "repeat": 1, "status": "success", "latency_ms": 1, "comparison": [], "metrics": []},
        {"provider": "groq", "case_id": case_id, "repeat": 2, "status": "error", "comparison": [], "metrics": [], "error": {"type": "TimeoutError"}},
    ]}))
    monkeypatch.setattr(judge_accuracy, "_make_judge", lambda provider: object())
    calls = []

    def success(provider, judge, case, repeat):
        calls.append(repeat)
        return {"provider": provider, "case_id": case_id, "repeat": repeat, "status": "success", "latency_ms": 1, "comparison": [], "metrics": []}

    monkeypatch.setattr(benchmark, "_run_case", success)
    result = benchmark.run(["groq"], repeats=2, output_path=output, resume=True)

    assert calls == [2]
    assert result["run_state"]["complete"] is True
    assert [run["repeat"] for run in result["runs"]] == [1, 2]
    assert result["run_state"]["resumed_prior_failures"][0]["repeat"] == 2


def test_matched_comparison_uses_only_exact_successful_keys():
    base_run = {
        "provider": "groq", "case_id": "c1", "repeat": 1, "status": "success",
        "comparison": [{
            "metric": "Goal Completion", "status": "compared", "score": 0.2,
            "absolute_error_to_midpoint": 0.1, "within_range": True,
            "expected_status": "fail", "actual_status": "fail", "status_agreement": True,
            "evidence_reference_valid": True,
        }],
    }
    after_run = json.loads(json.dumps(base_run))
    after_run["comparison"][0].update(score=0.9, within_range=False, actual_status="pass", status_agreement=False)
    common = {"deepeval_version": "2.0.9", "dataset": "cases.json", "configurations": [{"provider": "groq"}]}
    cases = [{
        "case_id": "c1",
        "labels": {"Goal Completion": {"score_range": [0.0, 0.4], "status": "fail"}},
    }]
    base_run["metrics"] = [{"name": "Goal Completion", "score": 0.2, "passed": False}]
    after_run["metrics"] = [{"name": "Goal Completion", "score": 0.9, "passed": True}]
    result = compare_benchmark_artifacts(
        {**common, "runs": [base_run]}, {**common, "runs": [after_run]}, cases=cases,
    )
    assert result["matched_sample_size"] == 1
    assert result["before"]["pass_fail_agreement"] == 1.0
    assert result["after"]["pass_fail_agreement"] == 0.0


def test_human_review_packets_are_blind_and_holdout_is_stable():
    benchmark = JudgeAccuracyBenchmark()
    first = build_review_packets(benchmark.cases, holdout_fraction=0.25)
    second = build_review_packets(benchmark.cases, holdout_fraction=0.25)
    assert [item["split"] for item in first["packets"]] == [item["split"] for item in second["packets"]]
    assert {item["split"] for item in first["packets"]} == {"development", "holdout"}
    assert all(item["judge_prediction"] is None for item in first["packets"])
    assert not any(item["current_reference"]["provenance"] == "human_reviewed" for item in first["packets"])
    assert validate_completed_reviews(first) == []
