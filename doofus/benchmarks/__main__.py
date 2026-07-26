"""CLI: run the held-out benchmark suite and emit a JSON report.

    python -m doofus.benchmarks [--out PATH] [--engine-ref REF]

Prints the overall and per-family scores; writes the full report as JSON when
--out is given.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from doofus.benchmarks.runner import report_to_dict, run_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m doofus.benchmarks")
    parser.add_argument("--out", type=Path, default=None, help="write JSON report to this path")
    parser.add_argument("--engine-ref", default="baseline", help="label identifying the engine state under test")
    args = parser.parse_args(argv)

    report = run_suite(engine_ref=args.engine_ref)
    payload = report_to_dict(report)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"suite_version   {report.suite_version}")
    print(f"engine_ref      {report.engine_ref}")
    print(f"isolation       {'verified' if report.isolation_verified else 'FAILED'}")
    print(f"tasks           {report.task_count}")
    for fam, score in sorted(report.family_scores.items()):
        print(f"  {fam:<14} {score:.4f}")
    print(f"overall_score   {report.overall_score:.4f}")
    if args.out is not None:
        print(f"report written  {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
