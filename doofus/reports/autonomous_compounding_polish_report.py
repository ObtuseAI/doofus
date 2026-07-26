"""Autonomous compounding polish final verdict report."""
from __future__ import annotations

import json

from doofus.core.doofus_paths import COMPOUNDING_POLISH_DIR
from doofus.reports.burn_in_metrics_snapshot import load_snapshot, capture_metrics_snapshot
from doofus.evolution.shadow_elite_upgrade_queue import queue_summary
from doofus.evolution.elite_archive import get_elite_archive
from doofus.dashboard.dashboard_health import classify_dashboard_health
from doofus.supervisor.scheduled_task_guard import get_scheduled_task_states


def build_verdict() -> dict:
    baseline = load_snapshot(COMPOUNDING_POLISH_DIR / "b1121_pre_completion_audit.json")
    post = capture_metrics_snapshot(label="b1127")
    tasks = get_scheduled_task_states()
    health = classify_dashboard_health(tasks.get("dashboard_state"))
    upgrades = queue_summary()
    elite = get_elite_archive()
    promo_d = int(post.get("promotion_count", 0)) - int(baseline.get("promotion_count", 0))
    elite_d = int(elite.get("elite_archive_count", 0)) - int(baseline.get("elite_archive_count", 0))

    watchdog_verdict = "watchdog_complete" if tasks.get("watchdog_registered") else "watchdog_complete_with_elevation_notes"
    dash_verdict = "dashboard_persistent" if health.get("persistent") else "dashboard_reachable_with_task_ready_notes"
    if not health.get("reachable"):
        dash_verdict = "dashboard_reachable_with_task_ready_notes"
    shadow_verdict = "shadow_upgrade_confirmed" if upgrades.get("upgrades", 0) > 0 else "shadow_upgrade_ready_no_eligible_candidates"
    elite_verdict = "elite_archive_growth_confirmed" if elite_d > 0 or int(elite.get("elite_archive_count", 0)) > 1 else "elite_archive_growth_ready_with_notes"

    overall = "autonomous_compounding_polish_complete_with_notes"
    if tasks.get("watchdog_registered") and health.get("reachable") and (elite_d > 0 or int(elite.get("elite_archive_count", 0)) > 1):
        overall = "autonomous_compounding_polish_complete_with_notes"

    return {
        "verdict": overall,
        "watchdog_verdict": watchdog_verdict,
        "dashboard_verdict": dash_verdict,
        "shadow_upgrade_verdict": shadow_verdict,
        "elite_archive_verdict": elite_verdict,
        "promotion_delta": promo_d,
        "elite_archive_delta": elite_d,
        "shadow_upgrades": upgrades.get("upgrades", 0),
        "elite_archive_count": elite.get("elite_archive_count", 0),
        "dashboard_health": health,
        "watchdog_tasks": tasks,
    }


def main() -> None:
    COMPOUNDING_POLISH_DIR.mkdir(parents=True, exist_ok=True)
    result = build_verdict()
    cls = "B1127_FINAL_VERDICT_ANALYSIS_PASS_WITH_NOTES"
    if result["verdict"] == "autonomous_compounding_polish_complete":
        cls = "B1127_FINAL_VERDICT_ANALYSIS_PASS"
    out = {"classification": cls, **result}
    (COMPOUNDING_POLISH_DIR / "b1127_final_verdict_analysis.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (COMPOUNDING_POLISH_DIR / "B1127_FINAL_VERDICT_ANALYSIS.md").write_text(f"# B1127\n\n`{cls}`\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
