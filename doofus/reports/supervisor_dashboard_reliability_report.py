"""Supervisor/dashboard reliability report for 12-hour run."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import STATE, TWELVE_HOUR_RUN_DIR

RUN_JSON = TWELVE_HOUR_RUN_DIR / "b1091_12_hour_unattended_run.json"


def build_report() -> dict:
    run = json.loads(RUN_JSON.read_text(encoding="utf-8")) if RUN_JSON.exists() else {}
    cps = run.get("checkpoints", [])
    sup_ready = sum(1 for c in cps if c.get("snapshot", {}).get("supervisor_task", {}).get("state") != "Running")
    dash_ready = sum(1 for c in cps if c.get("snapshot", {}).get("dashboard_task", {}).get("state") != "Running")
    stale_hb = sum(1 for c in cps if (c.get("snapshot", {}).get("heartbeat_age_seconds") or 0) > 300)
    dup_events = sum(1 for c in cps if (c.get("snapshot", {}).get("duplicate_pid_count") or 0) > 0)
    watch = {}
    wp = STATE / "watchdog_last.json"
    if wp.exists():
        watch = json.loads(wp.read_text(encoding="utf-8"))

    recs = []
    if dash_ready > len(cps) // 4:
        recs.append("repair_dashboard_task_restart")
    if stale_hb > 2:
        recs.append("increase_heartbeat_frequency")
    if dup_events > 3:
        recs.append("harden_cleanup_exclusion")
    if not recs:
        recs.append("no_change_needed")
    if watch.get("classification") == "WATCHDOG_ACTION":
        recs.append("register_watchdog_task")

    cls = "B1095_SUPERVISOR_DASHBOARD_RELIABILITY_PASS_WITH_NOTES"
    if dash_ready > len(cps) // 3 or stale_hb > len(cps) // 2:
        cls = "B1095_SUPERVISOR_DASHBOARD_RELIABILITY_FIX_RECOMMENDED"

    return {
        "classification": cls,
        "checkpoint_count": len(cps),
        "supervisor_not_running_checkpoints": sup_ready,
        "dashboard_not_running_checkpoints": dash_ready,
        "stale_heartbeat_checkpoints": stale_hb,
        "duplicate_pid_checkpoints": dup_events,
        "watchdog_last": watch.get("classification"),
        "recommendations": recs,
        "interrupted": run.get("status") == "interrupted",
    }


def main() -> None:
    r = build_report()
    TWELVE_HOUR_RUN_DIR.mkdir(parents=True, exist_ok=True)
    (TWELVE_HOUR_RUN_DIR / "b1095_supervisor_dashboard_reliability.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
    (TWELVE_HOUR_RUN_DIR / "B1095_SUPERVISOR_DASHBOARD_RELIABILITY.md").write_text(
        f"# B1095 Reliability\n\nClassification: `{r['classification']}`\n", encoding="utf-8"
    )
    print(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
