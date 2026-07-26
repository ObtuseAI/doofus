"""Proof-builder backlog runner - dry-run default, no live provider."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.proof.proof_builder_queue import pending_entries, queue_summary
from doofus.reports.cycle_finalizer import write_artifact_pair


def run_backlog(*, dry_run: bool, output_dir: Path, item_budget: int, time_budget_seconds: int) -> dict:
    summary = queue_summary()
    pending = pending_entries(min(item_budget, 500))
    processed = []
    if not dry_run:
        from doofus.proof.proof_builder_runner import process_one

        for entry in pending[:item_budget]:
            cid = entry.get("candidate_id")
            if not cid:
                continue
            processed.append({"candidate_id": cid, "result": process_one(cid)})
    else:
        for entry in pending[:item_budget]:
            processed.append(
                {
                    "candidate_id": entry.get("candidate_id"),
                    "simulated": True,
                    "outcome": "dry_run_would_process",
                }
            )

    payload = {
        "classification": "DOOFUS_PROOF_BUILDER_BACKLOG_DRY_RUN" if dry_run else "DOOFUS_PROOF_BUILDER_BACKLOG_RUN",
        "dry_run": dry_run,
        "queue_summary": summary,
        "item_budget": item_budget,
        "time_budget_seconds": time_budget_seconds,
        "processed_count": len(processed),
        "processed": processed,
        "live_route_invoked": False,
        "db_mutation": not dry_run,
    }
    write_artifact_pair(output_dir, "PROOF_BUILDER_FIRST_LANE_RESULT", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--item-budget", type=int, default=5)
    parser.add_argument("--time-budget-seconds", type=int, default=60)
    args = parser.parse_args()
    dry = not args.live
    payload = run_backlog(
        dry_run=dry,
        output_dir=Path(args.output_dir),
        item_budget=args.item_budget,
        time_budget_seconds=args.time_budget_seconds,
    )
    print(json.dumps({"classification": payload["classification"], "processed_count": payload["processed_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
