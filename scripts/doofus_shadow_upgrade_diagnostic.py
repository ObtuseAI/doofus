"""Read-only live-scale diagnostic for shadow elite upgrade batch."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.core.doofus_paths import METRICS_DB
from doofus.evolution.shadow_elite_upgrade_queue import process_upgrade_batch, queue_summary
from doofus.proof.inline_rescue_budget import (
    SHADOW_UPGRADE_DEFERRED_DEADLINE,
    policy_snapshot,
    shadow_upgrade_sub_deadline,
    should_defer_shadow_upgrade,
)


def write_pair(output_dir: Path, stem: str, payload: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# {stem}", "", f"**Classification:** `{payload.get('classification')}`", ""]
    for key, value in payload.items():
        if key == "classification":
            continue
        lines.append(f"- **{key}:** `{value}`")
    (output_dir / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_diagnostic(
    *,
    generation: int,
    limit: int,
    deadline_seconds: float,
    output_dir: Path,
    dry_run: bool = True,
    stem: str = "SHADOW_UPGRADE_DIAGNOSTIC",
) -> dict:
    started = time.perf_counter()
    deadline = time.monotonic() + deadline_seconds
    sub_deadline = shadow_upgrade_sub_deadline(deadline, init_phase=True)
    defer, defer_reason = should_defer_shadow_upgrade(sub_deadline, init_phase=True)
    summary_before = queue_summary()
    substeps: list[dict] = []

    t0 = time.perf_counter()
    substeps.append(
        {
            "step": "queue_summary",
            "duration_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "pending_upgrades": summary_before.get("pending_upgrades"),
        }
    )

    result: dict = {"classification": SHADOW_UPGRADE_DEFERRED_DEADLINE, "defer_reason": defer_reason, "processed": 0}
    if dry_run:
        t1 = time.perf_counter()
        result = process_upgrade_batch(
            limit=limit,
            baseline=0.5,
            deadline_monotonic=sub_deadline,
            init_phase=True,
            generation=generation,
            run_proof=False,
        )
        substeps.append(
            {
                "step": "process_upgrade_batch_dry_run",
                "duration_ms": round((time.perf_counter() - t1) * 1000.0, 2),
                "classification": result.get("classification"),
                "processed": result.get("processed"),
                "deferred": result.get("deferred"),
            }
        )
    elif not defer:
        t1 = time.perf_counter()
        result = process_upgrade_batch(
            limit=limit,
            baseline=0.5,
            deadline_monotonic=sub_deadline,
            init_phase=True,
            generation=generation,
            run_proof=True,
        )
        substeps.append(
            {
                "step": "process_upgrade_batch",
                "duration_ms": round((time.perf_counter() - t1) * 1000.0, 2),
                "classification": result.get("classification"),
                "processed": result.get("processed"),
            }
        )

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    within_deadline = elapsed_ms <= deadline_seconds * 1000.0 + 500.0
    ok_classifications = {
        "SHADOW_UPGRADE_OK",
        SHADOW_UPGRADE_DEFERRED_DEADLINE,
        "SHADOW_UPGRADE_PARTIAL",
    }
    passed = within_deadline and result.get("classification", "") in ok_classifications
    payload = {
        "classification": stem,
        "passed": passed,
        "generation": generation,
        "limit": limit,
        "deadline_seconds": deadline_seconds,
        "elapsed_ms": round(elapsed_ms, 2),
        "dry_run": dry_run,
        "readonly": dry_run,
        "defer_precheck": defer,
        "defer_reason": defer_reason,
        "budget_policy": policy_snapshot(),
        "queue_summary_before": summary_before,
        "result_classification": result.get("classification"),
        "result": result,
        "substeps": substeps,
        "live_db_mutated": not dry_run and result.get("processed", 0) > 0,
        "model_calls": 0,
        "provider_route_invoked": False,
    }
    write_pair(output_dir, stem, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only shadow upgrade diagnostic.")
    parser.add_argument("--generation", type=int, default=1640)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--deadline-seconds", type=float, default=30.0)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--stem", default="SHADOW_UPGRADE_DIAGNOSTIC")
    args = parser.parse_args()
    payload = run_diagnostic(
        generation=args.generation,
        limit=args.limit,
        deadline_seconds=args.deadline_seconds,
        output_dir=Path(args.output_dir),
        dry_run=args.dry_run,
        stem=args.stem,
    )
    print(json.dumps({"classification": payload["classification"], "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
