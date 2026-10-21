"""Controlled comparison of configured LLM judges against provisional labels."""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import google.generativeai as genai
from deepeval.models.base_model import DeepEvalBaseLLM

from app import evaluator
from app.config import settings
from app.schemas import Persona


DEFAULT_DATASET = Path(__file__).resolve().parents[2] / "benchmarks" / "judge_accuracy_cases.json"


class BenchmarkRateLimitError(RuntimeError):
    def __init__(self, message: str, *, limit_type: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.limit_type = limit_type
        self.retry_after_seconds = retry_after_seconds

    @property
    def quota_exhausted(self) -> bool:
        return self.limit_type == "tokens_per_day"


class GroqOnlyBenchmarkJudge(DeepEvalBaseLLM):
    """Production-equivalent Groq settings with fallback intentionally disabled."""

    provider = "groq"

    def __init__(self) -> None:
        from groq import Groq

        self.model_name = settings.groq_model
        self.client = Groq(api_key=settings.groq_api_key)
        self._quota_error: BenchmarkRateLimitError | None = None

    def load_model(self):
        return self.client

    def generate(self, prompt: str, schema=None):
        started = time.perf_counter()
        try:
            quota_error = getattr(self, "_quota_error", None)
            if quota_error is not None:
                raise quota_error
            if "json" not in prompt.lower():
                prompt += "\nRespond in JSON format."
            response = None
            for attempt in range(2):
                try:
                    response = self.client.chat.completions.create(
                        model=self.model_name,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.5,
                        max_completion_tokens=2048,
                        reasoning_effort="low",
                        include_reasoning=False,
                        response_format={"type": "json_object"},
                    )
                    break
                except Exception as exc:
                    rate_limit = _rate_limit_details(exc)
                    retry_after = (rate_limit or {}).get("retry_after_seconds")
                    retryable = bool(
                        rate_limit
                        and not rate_limit["quota_exhausted"]
                        and retry_after is not None
                        and retry_after <= 60
                        and attempt == 0
                    )
                    if not retryable:
                        raise
                    time.sleep(float(retry_after))
            if response is None:
                raise RuntimeError("Groq benchmark request produced no response.")
            text = evaluator._parse_and_validate_json(response.choices[0].message.content)
            usage = getattr(response, "usage", None)
            evaluator._record_judge_invocation(
                provider=self.provider,
                model=self.model_name,
                fallback_used=False,
                status="success",
                temperature=0.5,
                reasoning_effort="low",
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                token_usage=_groq_usage(usage),
            )
            return schema.model_validate_json(text) if schema is not None else text
        except Exception as exc:
            evaluator._record_judge_invocation(
                provider=self.provider, model=self.model_name, fallback_used=False,
                status="error", error=type(exc).__name__,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            rate_limit = _rate_limit_details(exc)
            if rate_limit:
                quota_error = BenchmarkRateLimitError(
                    str(exc),
                    limit_type=rate_limit["limit_type"],
                    retry_after_seconds=rate_limit["retry_after_seconds"],
                )
                if quota_error.quota_exhausted:
                    self._quota_error = quota_error
                raise quota_error from exc
            raise

    async def a_generate(self, prompt: str, schema=None):
        return self.generate(prompt, schema=schema)

    def get_model_name(self) -> str:
        return self.model_name


class GeminiOnlyBenchmarkJudge(DeepEvalBaseLLM):
    """Configured Gemini judge with no cross-provider fallback."""

    provider = "gemini"

    def __init__(self) -> None:
        self.model_name = settings.gemini_model
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel(model_name=self.model_name)

    def load_model(self):
        return self.model

    def generate(self, prompt: str, schema=None):
        started = time.perf_counter()
        try:
            response = self.model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json", temperature=0.5,
                ),
            )
            text = evaluator._parse_and_validate_json(response.text)
            evaluator._record_judge_invocation(
                provider=self.provider,
                model=self.model_name,
                fallback_used=False,
                status="success",
                temperature=0.5,
                reasoning_effort=None,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                token_usage=_gemini_usage(getattr(response, "usage_metadata", None)),
            )
            return schema.model_validate_json(text) if schema is not None else text
        except Exception as exc:
            evaluator._record_judge_invocation(
                provider=self.provider, model=self.model_name, fallback_used=False,
                status="error", error=type(exc).__name__,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise

    async def a_generate(self, prompt: str, schema=None):
        return self.generate(prompt, schema=schema)

    def get_model_name(self) -> str:
        return self.model_name


class JudgeAccuracyBenchmark:
    def __init__(self, dataset_path: str | Path = DEFAULT_DATASET) -> None:
        self.dataset_path = Path(dataset_path)
        self.cases = _load_cases(self.dataset_path)

    def run(
        self,
        providers: list[str],
        *,
        repeats: int = 3,
        case_ids: set[str] | None = None,
        output_path: str | Path | None = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        selected = [case for case in self.cases if not case_ids or case["case_id"] in case_ids]
        if not selected:
            raise ValueError("No benchmark cases matched the requested selection.")
        checkpoint_path = Path(output_path) if output_path else None
        resumed = _load_resume_runs(checkpoint_path) if resume and checkpoint_path else []
        selected_by_id = {case["case_id"]: case for case in selected}
        for run in resumed:
            case = selected_by_id.get(run.get("case_id"))
            if run.get("status") == "success" and case:
                run["comparison"] = _compare_case(case, run.get("metrics") or [])
        successful_keys = {
            _run_key(run) for run in resumed if run.get("status") == "success"
        }
        prior_failures = [run for run in resumed if run.get("status") != "success"]
        runs: list[dict[str, Any]] = [run for run in resumed if run.get("status") == "success"]
        stopped_reason: dict[str, Any] | None = None
        for provider in providers:
            judge = _make_judge(provider)
            for case in selected:
                for repeat in range(1, repeats + 1):
                    key = (provider, case["case_id"], repeat)
                    if key in successful_keys:
                        continue
                    run = self._run_case(provider, judge, case, repeat)
                    runs.append(run)
                    if checkpoint_path:
                        _write_checkpoint(checkpoint_path, self._result(
                            providers, selected, repeats, runs, prior_failures,
                            complete=False, stopped_reason=None,
                        ))
                    rate_limit = (run.get("error") or {}).get("rate_limit") or {}
                    if rate_limit.get("quota_exhausted"):
                        stopped_reason = {
                            "type": "quota_exhausted",
                            "provider": provider,
                            **rate_limit,
                        }
                        break
                if stopped_reason:
                    break
            if stopped_reason:
                break
        result = self._result(
            providers, selected, repeats, runs, prior_failures,
            complete=stopped_reason is None and len({_run_key(run) for run in runs if run.get("status") == "success"}) == len(providers) * len(selected) * repeats,
            stopped_reason=stopped_reason,
        )
        if checkpoint_path:
            _write_checkpoint(checkpoint_path, result)
        return result

    def _result(
        self,
        providers: list[str],
        selected: list[dict[str, Any]],
        repeats: int,
        runs: list[dict[str, Any]],
        prior_failures: list[dict[str, Any]],
        *,
        complete: bool,
        stopped_reason: dict[str, Any] | None,
    ) -> dict[str, Any]:
        expected_runs = len(providers) * len(selected) * repeats
        return {
            "benchmark": "EvalForge LLM Judge Accuracy Benchmark",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "deepeval_version": _package_version("deepeval"),
            "dataset": str(self.dataset_path),
            "case_count": len(selected),
            "repeats": repeats,
            "label_disclaimer": "Synthetic labels are deterministic or provisional; none are independently human-reviewed unless label_quality says human_reviewed.",
            "configurations": [_provider_configuration(provider) for provider in providers],
            "run_state": {
                "complete": complete,
                "expected_runs": expected_runs,
                "recorded_runs": len(runs),
                "successful_runs": sum(run.get("status") == "success" for run in runs),
                "stopped_reason": stopped_reason,
                "resumed_prior_failures": prior_failures,
            },
            "summary": _summarize(runs, selected),
            "runs": runs,
        }

    def _run_case(self, provider: str, judge: DeepEvalBaseLLM, case: dict[str, Any], repeat: int) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            with _isolated_judge(judge, set(case["applicable_metrics"])):
                results = evaluator.evaluate_transcript(
                    Persona.model_validate(case["persona"]),
                    case["conversation"],
                    rag_context=case.get("reference_evidence") or None,
                    expected_agent_persona=case.get("agent_expectations"),
                )
            metrics = [result.model_dump(mode="json") for result in results]
            metric_errors = [
                metric for metric in metrics
                if metric.get("evaluation_status") == "error"
            ]
            if metric_errors:
                error_message = "; ".join(
                    f"{metric['name']}: {metric.get('reason') or 'judge execution failed'}"
                    for metric in metric_errors
                )
                rate_limit = _rate_limit_details(RuntimeError(error_message))
                return {
                    "provider": provider,
                    "model": judge.get_model_name(),
                    "case_id": case["case_id"],
                    "repeat": repeat,
                    "status": "error",
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "label_quality": case["label_quality"],
                    "error": {
                        "type": "JudgeMetricError",
                        "message": error_message,
                        **({"rate_limit": rate_limit} if rate_limit else {}),
                    },
                    "metrics": metrics,
                    "comparison": [],
                }
            return {
                "provider": provider,
                "model": judge.get_model_name(),
                "case_id": case["case_id"],
                "repeat": repeat,
                "status": "success",
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "label_quality": case["label_quality"],
                "metrics": metrics,
                "comparison": _compare_case(case, metrics),
            }
        except Exception as exc:
            return {
                "provider": provider,
                "model": judge.get_model_name(),
                "case_id": case["case_id"],
                "repeat": repeat,
                "status": "error",
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "label_quality": case["label_quality"],
                "error": _error_details(exc),
                "metrics": [],
                "comparison": [],
            }


@contextmanager
def _isolated_judge(judge: DeepEvalBaseLLM, applicable_metrics: set[str]) -> Iterator[None]:
    original_judge = evaluator._judge
    original_builder = evaluator._build_metrics

    def selected_metrics(persona, rag_context, expected_agent_persona=None):
        return [
            metric for metric in original_builder(persona, rag_context, expected_agent_persona)
            if evaluator._metric_name(metric) in applicable_metrics
        ]

    evaluator._judge = judge
    evaluator._build_metrics = selected_metrics
    try:
        yield
    finally:
        evaluator._build_metrics = original_builder
        evaluator._judge = original_judge


def _make_judge(provider: str) -> DeepEvalBaseLLM:
    normalized = provider.strip().lower()
    if normalized == "groq":
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not configured.")
        return GroqOnlyBenchmarkJudge()
    if normalized == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        return GeminiOnlyBenchmarkJudge()
    raise ValueError(f"Unsupported benchmark provider: {provider}")


def _rate_limit_details(exc: Exception) -> dict[str, Any] | None:
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    message = str(exc)
    if status_code != 429 and "429" not in message and "rate limit" not in message.lower():
        return None

    lowered = message.lower()
    if "tokens per day" in lowered or "tpd" in lowered:
        limit_type = "tokens_per_day"
    elif "tokens per minute" in lowered or "tpm" in lowered:
        limit_type = "tokens_per_minute"
    elif "requests per minute" in lowered or "rpm" in lowered:
        limit_type = "requests_per_minute"
    else:
        limit_type = "other"

    retry_after = _retry_after_seconds(response, message)
    return {
        "status_code": 429,
        "limit_type": limit_type,
        "retry_after_seconds": retry_after,
        "quota_exhausted": limit_type == "tokens_per_day",
    }


def _retry_after_seconds(response: Any, message: str) -> float | None:
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("retry-after") or headers.get("Retry-After")
    if value is not None:
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            pass
    match = re.search(r"try again in\s+(?:(\d+)m)?\s*([\d.]+)s", message, re.I)
    if match:
        return round(float(match.group(1) or 0) * 60 + float(match.group(2)), 3)
    return None


def _error_details(exc: Exception) -> dict[str, Any]:
    details: dict[str, Any] = {"type": type(exc).__name__, "message": str(exc)}
    if isinstance(exc, BenchmarkRateLimitError):
        details["rate_limit"] = {
            "status_code": 429,
            "limit_type": exc.limit_type,
            "retry_after_seconds": exc.retry_after_seconds,
            "quota_exhausted": exc.quota_exhausted,
        }
    return details


def _run_key(run: dict[str, Any]) -> tuple[str, str, int]:
    return (str(run.get("provider")), str(run.get("case_id")), int(run.get("repeat") or 0))


def _load_resume_runs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    runs = payload.get("runs") or []
    if not isinstance(runs, list):
        raise ValueError(f"Resume artifact has invalid runs: {path}")
    return [run for run in runs if isinstance(run, dict)]


def _write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    serialized = json.dumps(payload, indent=2, ensure_ascii=True)
    temporary.write_text(serialized, encoding="utf-8")
    try:
        os.replace(temporary, path)
    except PermissionError:
        # Some managed Windows filesystems permit writes but deny atomic rename.
        path.write_text(serialized, encoding="utf-8")
        temporary.unlink(missing_ok=True)


def _load_cases(path: Path) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or len(cases) < 25:
        raise ValueError("Judge benchmark requires at least 25 cases.")
    required = {"case_id", "scenario", "persona", "conversation", "applicable_metrics", "labels", "label_quality", "rationale"}
    for index, case in enumerate(cases):
        missing = required - set(case)
        if missing:
            raise ValueError(f"Case {index} is missing fields: {sorted(missing)}")
        if case["label_quality"] not in {"deterministic", "provisional", "human_reviewed"}:
            raise ValueError(f"Case {case['case_id']} has invalid label_quality.")
    return cases


def _compare_case(case: dict[str, Any], metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actual = {metric["name"]: metric for metric in metrics}
    comparisons = []
    for name, label in case["labels"].items():
        metric = actual.get(name)
        if not metric:
            comparisons.append({"metric": name, "status": "missing"})
            continue
        low, high = label.get("score_range", [0.0, 1.0])
        score = metric.get("score")
        expected_status = label.get("status")
        evaluation_status = str(metric.get("evaluation_status") or "").lower()
        actual_status = (
            evaluation_status
            if evaluation_status in {"not_evaluated", "error"}
            else ("pass" if metric.get("passed") else "fail")
        )
        midpoint = (float(low) + float(high)) / 2
        expected_ids = set(label.get("expected_evidence_message_ids") or [])
        actual_id = metric.get("conversation_message_id")
        forbidden = [term.lower() for term in label.get("forbidden_reason_terms") or []]
        reason = str(metric.get("reason") or "")
        comparisons.append({
            "metric": name,
            "status": "compared",
            "score": score,
            "score_range": [low, high],
            "absolute_error_to_midpoint": None if score is None else round(abs(float(score) - midpoint), 6),
            "within_range": score is not None and float(low) <= float(score) <= float(high),
            "expected_status": expected_status,
            "actual_status": actual_status,
            "status_agreement": actual_status == expected_status,
            "evidence_reference_valid": not expected_ids or actual_id in expected_ids,
            "unsupported_explanation": any(term in reason.lower() for term in forbidden),
        })
    return comparisons


def _summarize(runs: list[dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for provider in sorted({run["provider"] for run in runs}):
        provider_runs = [run for run in runs if run["provider"] == provider]
        successful = [run for run in provider_runs if run["status"] == "success"]
        comparisons = [item for run in successful for item in run["comparison"] if item.get("status") == "compared"]
        scores = [item["absolute_error_to_midpoint"] for item in comparisons if item.get("absolute_error_to_midpoint") is not None]
        expected_fail = [item for item in comparisons if item.get("expected_status") == "fail"]
        expected_pass = [item for item in comparisons if item.get("expected_status") == "pass"]
        latencies = [float(run["latency_ms"]) for run in successful if run.get("latency_ms") is not None]
        contradiction_cases = {case["case_id"] for case in cases if "no_contradiction" in case.get("tags", [])}
        false_contradictions = [
            item for run in successful if run["case_id"] in contradiction_cases
            for item in run["comparison"]
            if item.get("metric") == "Multi-turn Consistency" and (
                item.get("actual_status") == "fail" or item.get("unsupported_explanation")
            )
        ]
        grouped_scores: dict[tuple[str, str], list[float]] = {}
        for run in successful:
            for metric in run["metrics"]:
                if metric.get("evaluation_status") not in {"not_evaluated", "error"}:
                    grouped_scores.setdefault((run["case_id"], metric["name"]), []).append(float(metric["score"]))
        variances = [statistics.pvariance(values) for values in grouped_scores.values() if len(values) > 1]
        summaries[provider] = {
            "runs": len(provider_runs),
            "successful_runs": len(successful),
            "failure_rate": _ratio(len(provider_runs) - len(successful), len(provider_runs)),
            "mean_absolute_score_error": round(statistics.mean(scores), 6) if scores else None,
            "scores_within_reference_range": _ratio(sum(bool(item.get("within_range")) for item in comparisons), len(comparisons)),
            "pass_fail_agreement": _ratio(sum(bool(item.get("status_agreement")) for item in comparisons), len(comparisons)),
            "context_retention_agreement": _metric_agreement(successful, "Context Retention"),
            "false_pass_rate": _ratio(sum(item.get("actual_status") == "pass" for item in expected_fail), len(expected_fail)),
            "false_fail_rate": _ratio(sum(item.get("actual_status") == "fail" for item in expected_pass), len(expected_pass)),
            "false_contradiction_rate": _ratio(len(false_contradictions), max(1, len(contradiction_cases) * max(1, len(provider_runs) // max(1, len(cases))))),
            "evidence_accuracy": _ratio(sum(bool(item.get("evidence_reference_valid")) for item in comparisons), len(comparisons)),
            "unsupported_explanation_rate": _ratio(sum(bool(item.get("unsupported_explanation")) for item in comparisons), len(comparisons)),
            "mean_repeated_run_variance": round(statistics.mean(variances), 8) if variances else 0.0,
            "status_changes": sum(len({"pass" if score >= _metric_threshold_for(group[0][1]) else "fail" for score in group[1]}) > 1 for group in grouped_scores.items()),
            "average_latency_ms": round(statistics.mean(latencies), 2) if latencies else None,
            "token_usage": _sum_token_usage(successful),
            "estimated_cost": None,
            "cost_note": "Not calculated because repository configuration does not contain versioned provider pricing.",
            "agreement_by_label_quality": {
                quality: _agreement_for_runs([run for run in successful if run.get("label_quality") == quality])
                for quality in ("deterministic", "provisional", "human_reviewed")
            },
            "per_metric": _per_metric_summary(successful),
        }
    return summaries


def _metric_threshold_for(name: str) -> float:
    return evaluator._metric_threshold(name)


def _agreement_for_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    comparisons = [item for run in runs for item in run.get("comparison", []) if item.get("status") == "compared"]
    errors = [item["absolute_error_to_midpoint"] for item in comparisons if item.get("absolute_error_to_midpoint") is not None]
    return {
        "comparisons": len(comparisons),
        "mean_absolute_score_error": round(statistics.mean(errors), 6) if errors else None,
        "scores_within_reference_range": _ratio(sum(bool(item.get("within_range")) for item in comparisons), len(comparisons)),
        "pass_fail_agreement": _ratio(sum(bool(item.get("status_agreement")) for item in comparisons), len(comparisons)),
    }


def _metric_agreement(runs: list[dict[str, Any]], metric_name: str) -> float | None:
    comparisons = [
        item for run in runs for item in run.get("comparison", [])
        if item.get("metric") == metric_name and item.get("status") == "compared"
    ]
    return _ratio(sum(bool(item.get("status_agreement")) for item in comparisons), len(comparisons))


def _per_metric_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        for item in run.get("comparison", []):
            if item.get("status") == "compared":
                grouped.setdefault(item["metric"], []).append(item)
    return {
        name: {
            "comparisons": len(items),
            "within_range": _ratio(sum(bool(item.get("within_range")) for item in items), len(items)),
            "pass_fail_agreement": _ratio(sum(bool(item.get("status_agreement")) for item in items), len(items)),
            "unsupported_explanation_rate": _ratio(sum(bool(item.get("unsupported_explanation")) for item in items), len(items)),
        }
        for name, items in sorted(grouped.items())
    }


def render_benchmark_markdown(result: dict[str, Any]) -> str:
    providers = [item["provider"] for item in result.get("configurations", [])]
    rows = [
        ("Scores within reference range", "scores_within_reference_range"),
        ("Mean absolute score error", "mean_absolute_score_error"),
        ("Pass/fail agreement", "pass_fail_agreement"),
        ("False pass rate", "false_pass_rate"),
        ("False fail rate", "false_fail_rate"),
        ("False contradiction rate", "false_contradiction_rate"),
        ("Context-retention agreement", "context_retention_agreement"),
        ("Evidence accuracy", "evidence_accuracy"),
        ("Unsupported explanation rate", "unsupported_explanation_rate"),
        ("Repeated-run variance", "mean_repeated_run_variance"),
        ("Average latency (ms)", "average_latency_ms"),
        ("Failure rate", "failure_rate"),
    ]
    lines = [
        "# EvalForge LLM Judge Accuracy Benchmark",
        "",
        f"Generated: {result.get('created_at')}",
        f"Dataset cases selected: {result.get('case_count')}",
        f"Repeats: {result.get('repeats')}",
        "",
        f"> {result.get('label_disclaimer')}",
        "",
        "## Model Comparison",
        "",
        "| Measurement | " + " | ".join(provider.title() for provider in providers) + " |",
        "|---|" + "---|" * len(providers),
    ]
    for label, key in rows:
        lines.append("| " + label + " | " + " | ".join(_display((result.get("summary", {}).get(provider) or {}).get(key)) for provider in providers) + " |")
    lines.extend(["", "## Label Quality", ""])
    for provider in providers:
        lines.append(f"### {provider.title()}")
        for quality, values in (result.get("summary", {}).get(provider, {}).get("agreement_by_label_quality") or {}).items():
            lines.append(f"- **{quality}:** {values.get('comparisons', 0)} comparisons; range agreement {_display(values.get('scores_within_reference_range'))}; pass/fail agreement {_display(values.get('pass_fail_agreement'))}")
        lines.append("")
    lines.extend(["## Provider Errors", ""])
    for provider in providers:
        failures = [run for run in result.get("runs", []) if run.get("provider") == provider and run.get("status") == "error"]
        lines.append(f"### {provider.title()} ({len(failures)} failed runs)")
        for run in failures[:20]:
            error = run.get("error") or {}
            lines.append(f"- `{run.get('case_id')}` repeat {run.get('repeat')}: {error.get('type')} - {error.get('message')}")
        lines.append("")
    lines.extend([
        "## Interpretation",
        "",
        "Results are benchmark measurements, not production score adjustments. A provider with quota failures or incomplete case coverage cannot be selected as the winning judge from this run.",
        "",
        "Raw per-case metrics, explanations, references, provenance, latency, and token diagnostics are retained in the companion JSON file.",
    ])
    return "\n".join(lines)


def compare_benchmark_artifacts(
    before: dict[str, Any],
    after: dict[str, Any],
    cases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    compatibility = {
        "deepeval_version_match": before.get("deepeval_version") == after.get("deepeval_version"),
        "dataset_match": Path(str(before.get("dataset"))).name == Path(str(after.get("dataset"))).name,
        "configuration_match": before.get("configurations") == after.get("configurations"),
    }
    case_index = {case["case_id"]: case for case in (cases or _load_cases(DEFAULT_DATASET))}
    before_rows = _comparison_rows(before, case_index)
    after_rows = _comparison_rows(after, case_index)
    matched_keys = sorted(set(before_rows) & set(after_rows))
    before_matched = [before_rows[key] for key in matched_keys]
    after_matched = [after_rows[key] for key in matched_keys]
    before_all_keys = set(before_rows)
    after_all_keys = set(after_rows)
    return {
        "compatibility": compatibility,
        "matched_sample_size": len(matched_keys),
        "matched_case_count": len({key[1] for key in matched_keys}),
        "matching_policy": "Exact provider, case ID, repeat number, and metric ID. Unsuccessful runs are absent from both populations.",
        "before": _comparison_summary(before_matched),
        "after": _comparison_summary(after_matched),
        "delta": _comparison_delta(before_matched, after_matched),
        "missing_from_after": [_key_payload(key) for key in sorted(before_all_keys - after_all_keys)],
        "not_in_baseline": [_key_payload(key) for key in sorted(after_all_keys - before_all_keys)],
        "selection_bias": (
            "The matched result excludes failed after-runs and all repeats absent from the one-repeat baseline. "
            "It is suitable for like-for-like comparison but not a substitute for a complete rerun."
        ),
    }


def _comparison_rows(
    payload: dict[str, Any],
    case_index: dict[str, dict[str, Any]],
) -> dict[tuple[str, str, int, str], dict[str, Any]]:
    rows: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    for run in payload.get("runs") or []:
        if run.get("status") != "success":
            continue
        case = case_index.get(str(run.get("case_id")))
        comparisons = _compare_case(case, run.get("metrics") or []) if case else (run.get("comparison") or [])
        for comparison in comparisons:
            if comparison.get("status") != "compared":
                continue
            key = (
                str(run.get("provider")), str(run.get("case_id")),
                int(run.get("repeat") or 0), str(comparison.get("metric")),
            )
            rows[key] = comparison
    return rows


def _comparison_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [row["absolute_error_to_midpoint"] for row in rows if row.get("absolute_error_to_midpoint") is not None]
    expected_pass = [row for row in rows if row.get("expected_status") == "pass"]
    expected_fail = [row for row in rows if row.get("expected_status") == "fail"]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("metric")), []).append(row)
    return {
        "comparisons": len(rows),
        "pass_fail_agreement": _ratio(sum(bool(row.get("status_agreement")) for row in rows), len(rows)),
        "score_range_agreement": _ratio(sum(bool(row.get("within_range")) for row in rows), len(rows)),
        "mean_absolute_score_error": round(statistics.mean(errors), 6) if errors else None,
        "evidence_accuracy": _ratio(sum(bool(row.get("evidence_reference_valid")) for row in rows), len(rows)),
        "false_pass_rate": _ratio(sum(row.get("actual_status") == "pass" for row in expected_fail), len(expected_fail)),
        "false_fail_rate": _ratio(sum(row.get("actual_status") == "fail" for row in expected_pass), len(expected_pass)),
        "per_metric": {
            name: {
                "comparisons": len(items),
                "pass_fail_agreement": _ratio(sum(bool(item.get("status_agreement")) for item in items), len(items)),
                "score_range_agreement": _ratio(sum(bool(item.get("within_range")) for item in items), len(items)),
            }
            for name, items in sorted(grouped.items())
        },
    }


def _comparison_delta(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    before_summary = _comparison_summary(before)
    after_summary = _comparison_summary(after)
    keys = (
        "pass_fail_agreement", "score_range_agreement", "mean_absolute_score_error",
        "evidence_accuracy", "false_pass_rate", "false_fail_rate",
    )
    return {
        key: None if before_summary[key] is None or after_summary[key] is None else round(after_summary[key] - before_summary[key], 6)
        for key in keys
    }


def _key_payload(key: tuple[str, str, int, str]) -> dict[str, Any]:
    return {"provider": key[0], "case_id": key[1], "repeat": key[2], "metric": key[3]}


def _display(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _sum_token_usage(runs: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for run in runs:
        for metric in run.get("metrics", []):
            for invocation in (metric.get("diagnostics") or {}).get("judge_invocations", []):
                usage = invocation.get("token_usage") or {}
                for key in totals:
                    totals[key] += int(usage.get(key) or 0)
    return totals


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _groq_usage(usage: Any) -> dict[str, int]:
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


def _gemini_usage(usage: Any) -> dict[str, int]:
    return {
        "prompt_tokens": int(getattr(usage, "prompt_token_count", 0) or 0),
        "completion_tokens": int(getattr(usage, "candidates_token_count", 0) or 0),
        "total_tokens": int(getattr(usage, "total_token_count", 0) or 0),
    }


def _provider_configuration(provider: str) -> dict[str, Any]:
    if provider == "groq":
        return {"provider": "groq", "model": settings.groq_model, "temperature": 0.5, "reasoning_effort": "low", "fallback": False}
    return {"provider": "gemini", "model": settings.gemini_model, "temperature": 0.5, "reasoning_effort": None, "fallback": False}


def _package_version(name: str) -> str:
    from importlib.metadata import version
    return version(name)

