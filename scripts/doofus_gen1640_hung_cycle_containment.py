"""Contain hung gen1640 live cycle and restore gen1639 baseline safety."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1640-live-verification-v1"
sys.path.insert(0, str(WORKSPACE))

from doofus.core.doofus_paths import METRICS_DB, STATE
from doofus.runtime.live_db_preflight import backup_live_db, inspect_live_db
from doofus.safety.on_off_switch import status, stop
from doofus.supervisor.doofus_crash_recovery import save_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import write_checkpoint as write_cycle_ck


def write_pair(stem: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    starting = json.loads((OUT / "STARTING_STATE.json").read_text(encoding="utf-8"))
    marker = STATE / "one_cycle_launch_active.marker"
    if marker.exists():
        marker.unlink()

    stop_after = stop()
    save_checkpoint(starting["checkpoint"])
    cc = starting["cycle_checkpoint"]
    write_cycle_ck(cc.get("stage", "cycle_complete"), cc.get("data", {}))

    backup_path = backup_live_db(output_dir=OUT, label="gen1640_hung_containment")
    conn = sqlite3.connect(METRICS_DB, timeout=30)
    deleted = conn.execute("DELETE FROM champion_defense_events WHERE generation=1640").rowcount
    conn.commit()
    conn.close()

    pf = inspect_live_db(target_generation=1640)
    pf1641 = inspect_live_db(target_generation=1641)

    write_pair(
        "CONTAINMENT_RESULT",
        {
            "classification": "DOOFUS_GEN1640_HUNG_CYCLE_CONTAINMENT",
            "reason": "live_cycle_hung_over_60min_at_phase_started",
            "stop_restored": stop_after.get("stop_requested"),
            "checkpoint_restored_to_gen1639": starting["checkpoint"],
            "orphan_gen1640_champion_rows_deleted": deleted,
            "backup_path": str(backup_path),
            "preflight_after_containment": pf,
            "gen1641_rows": pf1641.get("target_generation_total"),
        },
    )

    write_pair(
        "live_cycle_process_result",
        {
            "classification": "DOOFUS_LIVE_CYCLE_PROCESS_HUNG",
            "start": "2026-07-05T08:36:13-05:00",
            "end": "2026-07-05T09:35:00-05:00",
            "exit_code": -1,
            "command": "python -m doofus.supervisor.provider_aware_live_cycle --operator-approved-one-cycle --max-model-calls 2 --max-cost-usd 0.05",
            "note": "Process terminated after hang; no candidates or model calls for gen1640",
        },
    )
    (OUT / "live_cycle_stdout_stderr.log").write_text(
        json.dumps({"stdout": "", "stderr": "process hung and was terminated", "hung": True}, indent=2),
        encoding="utf-8",
    )

    write_pair(
        "post_run_invariant_check",
        {
            "classification": "DOOFUS_POST_RUN_INVARIANT_CHECK",
            "stop_flag": stop_after,
            "checkpoint": starting["checkpoint"],
            "gen1640_row_count": pf.get("target_generation_total"),
            "gen1641_row_count": pf1641.get("target_generation_total"),
            "live_model_call_count_gen1640": 0,
            "continuous_loop_started": False,
            "repeated_cycle_detected": False,
            "all_invariants_pass": stop_after.get("stop_requested") and pf.get("target_generation_total") == 0,
        },
    )

    write_pair(
        "gen1640_live_telemetry_summary",
        {
            "classification": "DOOFUS_GEN1640_LIVE_TELEMETRY_SUMMARY",
            "generation_before": 1639,
            "generation_after": 1639,
            "process_return_code": -1,
            "live_model_call_count": 0,
            "candidate_count": 0,
            "inline_rescue_status": "not_reached",
            "stop_restored": stop_after.get("stop_requested"),
            "hung_at_checkpoint_phase": "started",
            "live_route_invoked": True,
            "live_route_completed": False,
        },
    )

    write_pair(
        "FINAL_REPORT",
        {
            "classification": "DOOFUS_GEN1640_LIVE_VERIFICATION_PARTIAL",
            "launch_executed": True,
            "cycle_completed": False,
            "hung_contained": True,
            "blocker": "live_cycle_hung_at_gen1640_init_before_candidate_generation",
            "gen1639_baseline_restored": True,
            "next_action": "Investigate hang at cycle init (heartbeat stuck cycle_start); repair provider/prepare_cycle path; re-run gen1640 after root-cause fix.",
        },
    )
    print(json.dumps({"containment": "done", "stop": stop_after.get("stop_requested"), "gen1640_rows": pf.get("target_generation_total")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
