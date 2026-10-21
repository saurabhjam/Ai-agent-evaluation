"""Blind human-review packets for judge benchmark ground-truth collection."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.evaluator import METRIC_CONFIG


def build_review_packets(cases: list[dict[str, Any]], *, holdout_fraction: float = 0.2) -> dict[str, Any]:
    if not 0 <= holdout_fraction < 1:
        raise ValueError("holdout_fraction must be at least 0 and less than 1.")
    packets = []
    for case in cases:
        split = _stable_split(case["case_id"], holdout_fraction)
        for metric_name, label in case["labels"].items():
            packets.append({
                "case_id": case["case_id"],
                "split": split,
                "scenario": case["scenario"],
                "conversation": case["conversation"],
                "metric_name": metric_name,
                "metric_definition": (METRIC_CONFIG.get(metric_name) or {}).get("description"),
                "current_reference": {
                    "score_range": label.get("score_range"),
                    "status": label.get("status"),
                    "provenance": case.get("label_quality"),
                    "expected_evidence": case.get("expected_evidence"),
                    "rationale": case.get("rationale"),
                },
                "judge_prediction": None,
                "review": {
                    "reviewer_score": None,
                    "reviewer_status": None,
                    "reasoning": None,
                    "evidence_message_ids": [],
                    "reviewer_id": None,
                    "reviewed_at": None,
                    "disagreement_status": "unreviewed",
                    "adjudication": None,
                },
            })
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "blind_review": True,
        "prediction_visibility": "Judge predictions are intentionally omitted.",
        "holdout_policy": "Stable SHA-256 case split; holdout records must not be used for prompt tuning.",
        "packets": packets,
    }


def validate_completed_reviews(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for index, packet in enumerate(payload.get("packets") or []):
        review = packet.get("review") or {}
        if review.get("disagreement_status") == "unreviewed":
            continue
        if review.get("reviewer_score") is None:
            errors.append(f"Packet {index} is missing reviewer_score.")
        if review.get("reviewer_status") not in {"pass", "fail", "not_evaluated"}:
            errors.append(f"Packet {index} has invalid reviewer_status.")
        if not str(review.get("reasoning") or "").strip():
            errors.append(f"Packet {index} is missing reasoning.")
        if not str(review.get("reviewer_id") or "").strip():
            errors.append(f"Packet {index} is missing reviewer_id.")
        if not str(review.get("reviewed_at") or "").strip():
            errors.append(f"Packet {index} is missing reviewed_at.")
    return errors


def _stable_split(case_id: str, holdout_fraction: float) -> str:
    bucket = int(hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "holdout" if bucket < holdout_fraction else "development"
