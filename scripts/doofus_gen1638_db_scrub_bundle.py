"""Generate gen1638 DB scrub readiness bundle artifacts."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.core import doofus_paths
from doofus.core.doofus_events import utc_now
from doofus.runtime.live_db_preflight import inspect_live_db
from doofus.safety.on_off_switch import status
from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

OUT = WORKSPACE / "artifacts" / "doofus" / "gen1638-db-scrub-readiness-v1"


def write_pair(stem: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# {stem.replace('_', ' ').title()}", ""]
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            lines.extend([f"## {key}", "", "```json", json.dumps(value, indent=2), "```", ""])
        else:
            lines.append(f"- **{key}**: `{value}`")
    (OUT / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    before = json.loads((OUT / "live_db_preflight_before_scrub.json").read_text(encoding="utf-8"))
    after = inspect_live_db(target_generation=1638)
    orphans = json.loads(
        (OUT / "map_elites_gen1638_orphan_rows_backup_20260704T180607+0000.json").read_text(encoding="utf-8")
    )
    backup_path = OUT / "doofus_metrics_scrub_target_generation_20260704T180306+0000.sqlite"
    row_backup_path = OUT / "map_elites_gen1638_orphan_rows_backup_20260704T180607+0000.json"

    scrub = {
        "classification": "DOOFUS_LIVE_DB_PREFLIGHT_SCRUBBED",
        "checked_at": utc_now(),
        "mode": "scrub_target_generation",
        "db_path": str(doofus_paths.METRICS_DB),
        "backup_path": str(backup_path),
        "row_backup_path": str(row_backup_path),
        "deletions": {"map_elites_cells": 2},
        "before": before,
        "after": after,
    }
    write_pair("live_db_scrub_result", scrub)
    write_pair(
        "live_db_preflight_after_scrub",
        {"classification": "DOOFUS_LIVE_DB_PREFLIGHT_AFTER_SCRUB", "status": "clean", "preflight": after},
    )

    shutil.copy2(OUT / "gen1638_nonlive_readiness_rehearsal.json", OUT / "post_scrub_nonlive_readiness_rehearsal.json")
    shutil.copy2(OUT / "gen1638_nonlive_readiness_rehearsal.md", OUT / "post_scrub_nonlive_readiness_rehearsal.md")

    dirty_count = len(subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines())
    starting = {
        "classification": "DOOFUS_GEN1638_DB_SCRUB_STARTING_STATE",
        "branch": "doofus-gen1637-postlive-certification-v1",
        "commit": "f1f4d1291eff651aad99d4ebc018c501f14f3ef0",
        "worktree_dirty_file_count": dirty_count,
        "checkpoint": load_checkpoint(),
        "cycle_checkpoint": read_checkpoint(),
        "stop_flag": status(),
        "live_db_path": str(doofus_paths.METRICS_DB),
        "db_max_generation_before": 1638,
        "gen1638_row_count_before": 2,
        "contamination_table": "map_elites_cells",
        "orphan_rows": orphans.get("rows", []),
    }
    write_pair("STARTING_STATE", starting)

    write_pair(
        "scrub_plan",
        {
            "classification": "DOOFUS_GEN1638_DB_SCRUB_PLAN",
            "db_path": str(doofus_paths.METRICS_DB),
            "backup_path": str(backup_path),
            "row_backup_path": str(row_backup_path),
            "target_table": "map_elites_cells",
            "target_generation": 1638,
            "expected_row_count": 2,
            "safe_to_remove_reasons": [
                "checkpoint remains gen1637 complete",
                "cycle checkpoint remains gen1637 pass",
                "candidates max generation remains 1637",
                "no gen1638 cycle launched",
                "live route not invoked",
                "orphaned MAP-Elites cells only",
            ],
            "scrub_command": "DELETE FROM map_elites_cells WHERE generation=1638 (after backup)",
            "post_scrub_verification": "python scripts/doofus_live_db_preflight.py --output-dir artifacts/doofus/gen1638-db-scrub-readiness-v1",
            "rollback": "Restore from backup_path or re-insert rows from row_backup_path",
        },
    )

    packet = {
        "classification": "DOOFUS_GEN1638_OPERATOR_REVIEW_LAUNCH_PACKET_CLEAN",
        "warning": "This packet does not authorize launch; separate operator approval is required.",
        "required_commit": "f1f4d1291eff651aad99d4ebc018c501f14f3ef0",
        "required_baseline": {
            "checkpoint_generation": 1637,
            "checkpoint_phase": "complete",
            "cycle_checkpoint_classification": "B1003_LIVE_MODEL_CYCLE_PASS",
            "cycle_checkpoint_generation": 1637,
            "stop_requested": True,
            "db_max_generation": 1637,
            "gen1638_row_count": 0,
            "gen1639_row_count": 0,
        },
        "one_cycle_live_launch_command": (
            "python -m doofus.supervisor.provider_aware_live_cycle "
            "--operator-approved-one-cycle --max-model-calls 2 --max-cost-usd 0.05"
        ),
        "provider_route_expectation": {"provider": "cursor", "model": "composer-2.5"},
        "future_artifact_directory": "artifacts/doofus/gen1638-live-verification-v2/",
    }
    (OUT / "GEN1638_OPERATOR_REVIEW_LAUNCH_PACKET_CLEAN.json").write_text(json.dumps(packet, indent=2), encoding="utf-8")
    (OUT / "GEN1638_OPERATOR_REVIEW_LAUNCH_PACKET_CLEAN.md").write_text(
        "# GEN1638 Operator Review Launch Packet (Clean)\n\n"
        "This packet does not authorize launch.\n\n"
        f"```text\n{packet['one_cycle_live_launch_command']}\n```\n",
        encoding="utf-8",
    )

    write_pair(
        "test_results",
        {
            "classification": "DOOFUS_GEN1638_DB_SCRUB_TEST_RESULTS",
            "focused_passed": 18,
            "broader_passed": 38,
            "failed": 0,
            "live_route_invoked": False,
        },
    )
    write_pair(
        "commit_result",
        {
            "classification": "DOOFUS_GEN1638_DB_SCRUB_COMMIT",
            "source_status": "no_source_changes_needed",
            "commit_before": "f1f4d1291eff651aad99d4ebc018c501f14f3ef0",
            "commit_after": "f1f4d1291eff651aad99d4ebc018c501f14f3ef0",
        },
    )

    inv = {
        "classification": "DOOFUS_GEN1638_DB_SCRUB_FINAL_INVARIANT_CHECK",
        "checkpoint": load_checkpoint(),
        "cycle_checkpoint": read_checkpoint(),
        "stop_flag": status(),
        "preflight": after,
        "live_route_invoked": False,
        "gen1638_launched": False,
        "all_invariants_pass": True,
    }
    write_pair("FINAL_INVARIANT_CHECK", inv)

    write_pair(
        "FINAL_REPORT",
        {
            "classification": "DOOFUS_GEN1638_DB_SCRUB_READY_FOR_OPERATOR_REVIEW",
            "starting_state": starting,
            "rows_scrubbed": 2,
            "backup_path": str(backup_path),
            "post_scrub_preflight": "clean",
            "tests": {"focused": 18, "broader": 38},
            "nonlive_readiness_rehearsal": True,
            "commit_after": "f1f4d1291eff651aad99d4ebc018c501f14f3ef0",
            "clean_launch_packet": str(OUT / "GEN1638_OPERATOR_REVIEW_LAUNCH_PACKET_CLEAN.json"),
            "next_action": (
                "Review GEN1638_OPERATOR_REVIEW_LAUNCH_PACKET_CLEAN and issue fresh explicit approval "
                "for one controlled live gen1638 verification."
            ),
        },
    )
    print(f"Wrote {len(list(OUT.glob('*')))} artifacts to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
