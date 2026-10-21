"""Export blind development and holdout packets for independent benchmark review."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.benchmarks.human_review import build_review_packets, validate_completed_reviews


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("benchmarks/judge_accuracy_cases.json"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/human_review_packets.json"))
    parser.add_argument("--holdout-fraction", type=float, default=0.2)
    parser.add_argument("--validate", type=Path)
    args = parser.parse_args()

    if args.validate:
        errors = validate_completed_reviews(json.loads(args.validate.read_text(encoding="utf-8")))
        print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
        return 1 if errors else 0

    cases = json.loads(args.dataset.read_text(encoding="utf-8"))
    payload = build_review_packets(cases, holdout_fraction=args.holdout_fraction)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output.resolve()),
        "packets": len(payload["packets"]),
        "development": sum(item["split"] == "development" for item in payload["packets"]),
        "holdout": sum(item["split"] == "holdout" for item in payload["packets"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
