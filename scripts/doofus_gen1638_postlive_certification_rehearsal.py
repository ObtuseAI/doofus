"""Non-live post-gen1638 certification rehearsal using isolated runtime."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.runtime.live_db_preflight import inspect_live_db
from doofus.safety.on_off_switch import status
from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint
from doofus.supervisor.live_cycle_launch_guard import verify_nonlive_dry_run_guard
from scripts.doofus_nonlive_certification_rehearsal import run_rehearsal


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-gen1638 non-live certification rehearsal.")
    parser.add_argument(
        "--output-dir",
        default=str(WORKSPACE / "artifacts" / "doofus" / "gen1638-postlive-certification-v1"),
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    canonical_preflight = inspect_live_db(target_generation=1639)
    checkpoint = load_checkpoint()
    cycle = read_checkpoint()
    stop_before = status()

    rehearsal = run_rehearsal(output_dir=output_dir, stem="postlive_nonlive_certification_rehearsal")
    stop_after = status()
    checkpoint_after = load_checkpoint()
    cycle_after = read_checkpoint()
    preflight_after = inspect_live_db(target_generation=1639)

    passed = all([
        checkpoint.get("generation") == 1638,
        checkpoint.get("phase") == "complete",
        cycle.get("data", {}).get("generation") == 1638,
        canonical_preflight.get("db_max_generation") == 1638,
        canonical_preflight.get("target_generation_total") == 0,
        rehearsal.get("model_classification") == "DOOFUS_MODEL_DRY_RUN",
        rehearsal.get("live_model_rows_inserted") == 0,
        rehearsal.get("checkpoint_promoted") is False,
        stop_after.get("stop_requested") is True,
        checkpoint_after.get("generation") == 1638,
        cycle_after.get("data", {}).get("generation") == 1638,
        preflight_after.get("target_generation_total") == 0,
    ])

    report = {
        "classification": "DOOFUS_GEN1638_POSTLIVE_NONLIVE_CERTIFICATION_REHEARSAL",
        "readiness_passed": passed,
        "canonical_preflight_gen1639": canonical_preflight,
        "preflight_after": preflight_after,
        "rehearsal": rehearsal,
        "stop_before": stop_before,
        "stop_after": stop_after,
        "checkpoint_unchanged": checkpoint == checkpoint_after,
    }
    (output_dir / "postlive_nonlive_certification_rehearsal.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = [
        "# Post-Live Non-Live Certification Rehearsal",
        "",
        f"- classification: `{report['classification']}`",
        f"- readiness_passed: `{passed}`",
        f"- nonlive_guard: `{verify_nonlive_dry_run_guard().get('classification')}`",
        f"- checkpoint_unchanged: `{report['checkpoint_unchanged']}`",
    ]
    (output_dir / "postlive_nonlive_certification_rehearsal.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
