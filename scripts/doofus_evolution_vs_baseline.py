"""Run the bounded evolution-vs-held-out-baseline experiment."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doofus.experiments.evolution_vs_baseline import write_report  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generations", type=int, default=24)
    parser.add_argument("--engine-ref", default="working-tree")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/benchmarks/evolution_vs_baseline_report.json"),
    )
    args = parser.parse_args(argv)
    report = write_report(args.out, generations=args.generations, engine_ref=args.engine_ref)
    heldout = report["heldout"]
    print(f"training delta: {report['training_fitness']['delta']:+.6f}")
    print(f"held-out delta: {heldout['overall_delta']:+.6f}")
    print(f"improved: {heldout['improved']}")
    print(f"report: {args.out}")
    return 0 if heldout["isolation_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
