"""CLI: candidate quality report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from doofus.evaluation.candidate_quality import analyze_generations
from doofus.reports.cycle_finalizer import write_artifact_pair


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start-generation", type=int, default=1637)
    parser.add_argument("--end-generation", type=int, default=1642)
    args = parser.parse_args()
    out = Path(args.output_dir)
    payload = analyze_generations(start_generation=args.start_generation, end_generation=args.end_generation)
    write_artifact_pair(out, "candidate_quality_report", payload)
    print(json.dumps({"classification": payload["classification"], "dominant": payload.get("aggregate_dominant_rejection_reason")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
