"""CLI: promotion near-miss report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from doofus.evaluation.promotion_near_miss import analyze_generations_near_miss, find_near_misses
from doofus.reports.cycle_finalizer import write_artifact_pair


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--generation", type=int, default=1642)
    parser.add_argument("--start-generation", type=int, default=None)
    parser.add_argument("--end-generation", type=int, default=None)
    args = parser.parse_args()
    out = Path(args.output_dir)
    if args.start_generation is not None and args.end_generation is not None:
        payload = analyze_generations_near_miss(args.start_generation, args.end_generation)
    else:
        payload = find_near_misses(args.generation)
    write_artifact_pair(out, "promotion_near_miss_report", payload)
    print(json.dumps({"classification": payload["classification"], "best": payload.get("best_near_miss_candidate")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
