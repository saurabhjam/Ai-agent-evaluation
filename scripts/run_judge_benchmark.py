"""Run the isolated EvalForge judge-accuracy benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.benchmarks.judge_accuracy import JudgeAccuracyBenchmark, render_benchmark_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("groq", "gemini", "both"), default="both")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--case", action="append", dest="cases", help="Run only this case ID; may be repeated.")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/benchmarks/judge-accuracy.json"))
    parser.add_argument("--resume", action="store_true", help="Resume from --output without repeating successful runs.")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    benchmark = JudgeAccuracyBenchmark(args.dataset) if args.dataset else JudgeAccuracyBenchmark()
    if args.validate_only:
        print(json.dumps({"valid": True, "case_count": len(benchmark.cases), "dataset": str(benchmark.dataset_path)}, indent=2))
        return 0

    providers = ["groq", "gemini"] if args.provider == "both" else [args.provider]
    result = benchmark.run(
        providers,
        repeats=args.repeats,
        case_ids=set(args.cases or []),
        output_path=args.output,
        resume=args.resume,
    )
    markdown_path = args.output.with_suffix(".md")
    markdown_path.write_text(render_benchmark_markdown(result), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Full benchmark written to {args.output.resolve()}")
    print(f"Readable report written to {markdown_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
