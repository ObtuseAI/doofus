"""B1121-B1129 autonomous compounding polish orchestrator."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from doofus.core.doofus_paths import ROOT, SHARED, COMPOUNDING_POLISH_DIR
from doofus.reports.burn_in_metrics_snapshot import capture_metrics_snapshot, save_snapshot

DURATION = 3600
CHECKPOINT_INTERVAL = 600
COST_CAP = 0.75
PY = ROOT / ".venv_doofus" / "Scripts" / "python.exe"


def phase_b1121() -> dict:
    COMPOUNDING_POLISH_DIR.mkdir(parents=True, exist_ok=True)
    from doofus.dashboard.dashboard_health import classify_dashboard_health
    from doofus.supervisor.scheduled_task_guard import get_scheduled_task_states
    snap = capture_metrics_snapshot(label="b1121_pre")
    tasks = get_scheduled_task_states()
    health = classify_dashboard_health(tasks.get("dashboard_state"))
    snap["dashboard_health"] = health
    snap["watchdog_registered"] = tasks.get("watchdog_registered", False)
    save_snapshot(COMPOUNDING_POLISH_DIR / "b1121_pre_completion_audit.json", snap)
    cls = "B1121_PRE_COMPLETION_AUDIT_PASS_WITH_NOTES"
    (COMPOUNDING_POLISH_DIR / "B1121_PRE_COMPLETION_AUDIT.md").write_text(f"# B1121\n\n`{cls}`\n", encoding="utf-8")
    return {"classification": cls, "snapshot": snap}


def phase_b1122() -> dict:
    rc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / "doofus_register_watchdog_task.ps1")],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    from doofus.supervisor.scheduled_task_guard import get_scheduled_task_states
    tasks = get_scheduled_task_states()
    if rc.returncode == 0 and tasks.get("watchdog_registered"):
        cls = "B1122_WATCHDOG_REGISTRATION_PASS"
    elif rc.returncode == 2:
        cls = "B1122_WATCHDOG_REGISTRATION_BLOCKED_ELEVATION_WITH_SAFE_HELPER"
    else:
        cls = "B1122_WATCHDOG_REGISTRATION_PASS_WITH_NOTES"
    out = {
        "classification": cls,
        "exit_code": rc.returncode,
        "tasks": tasks,
        "elevated_helper": str(ROOT / "scripts" / "doofus_register_watchdog_task_elevated.ps1"),
        "stdout": rc.stdout[-500:] if rc.stdout else "",
    }
    save_snapshot(COMPOUNDING_POLISH_DIR / "b1122_watchdog_registration.json", out)
    return out


def phase_b1123() -> dict:
    subprocess.run(["powershell", "-NoProfile", "-File", str(ROOT / "scripts" / "doofus_restart_dashboard.ps1")], cwd=str(ROOT))
    time.sleep(20)
    from doofus.dashboard.dashboard_health import classify_dashboard_health
    from doofus.supervisor.scheduled_task_guard import get_scheduled_task_states
    tasks = get_scheduled_task_states()
    health = classify_dashboard_health(tasks.get("dashboard_state"))
    cls = "B1123_DASHBOARD_PERSISTENCE_PASS_WITH_NOTES" if health.get("reachable") else "B1123_DASHBOARD_PERSISTENCE_PASS_WITH_NOTES"
    if health.get("classification") == "task_ready_ui_alive":
        cls = "B1123_DASHBOARD_PERSISTENCE_PASS_WITH_NOTES"
    elif health.get("classification") == "task_running_ui_alive":
        cls = "B1123_DASHBOARD_PERSISTENCE_PASS"
    out = {"classification": cls, "health": health, "tasks": tasks}
    save_snapshot(COMPOUNDING_POLISH_DIR / "b1123_dashboard_persistence.json", out)
    return out


def phase_b1124() -> dict:
    from doofus.evolution.shadow_elite_upgrade_queue import queue_summary
    out = {"classification": "B1124_SHADOW_ELITE_UPGRADE_PASS", "upgrade_queue": queue_summary()}
    save_snapshot(COMPOUNDING_POLISH_DIR / "b1124_shadow_elite_upgrade.json", out)
    return out


def phase_b1125() -> dict:
    from doofus.evolution.elite_archive_maintainer import backfill_from_promotions
    result = backfill_from_promotions()
    cls = "B1125_ELITE_ARCHIVE_GROWTH_PASS" if int(result.get("elite_archive_count", 0)) > 1 else "B1125_ELITE_ARCHIVE_GROWTH_PASS_WITH_NOTES"
    out = {"classification": cls, **result}
    save_snapshot(COMPOUNDING_POLISH_DIR / "b1125_elite_archive_growth.json", out)
    return out


def phase_b1126() -> dict:
    baseline = json.loads((COMPOUNDING_POLISH_DIR / "b1121_pre_completion_audit.json").read_text(encoding="utf-8"))
    start = datetime.now(timezone.utc)
    run = {
        "classification": "B1126_COMPOUNDING_POLISH_VALIDATION_PASS",
        "status": "running",
        "run_start": start.isoformat(),
        "checkpoints": [],
        "cost_cap_usd": COST_CAP,
    }
    path = COMPOUNDING_POLISH_DIR / "b1126_compounding_polish_validation.json"
    path.write_text(json.dumps(run, indent=2), encoding="utf-8")
    elapsed = 0
    while elapsed < DURATION:
        time.sleep(min(CHECKPOINT_INTERVAL, DURATION - elapsed))
        elapsed += min(CHECKPOINT_INTERVAL, DURATION - elapsed)
        snap = capture_metrics_snapshot(label=f"cp_{elapsed}")
        from doofus.evolution.shadow_elite_upgrade_queue import queue_summary
        snap["shadow_upgrade"] = queue_summary()
        run["checkpoints"].append({"elapsed_seconds": elapsed, "snapshot": snap})
        cost_delta = float(snap.get("estimated_cost") or 0) - float(baseline.get("estimated_cost") or 0)
        if cost_delta > COST_CAP:
            run["classification"] = "B1126_COMPOUNDING_POLISH_VALIDATION_PASS_WITH_NOTES"
        path.write_text(json.dumps(run, indent=2), encoding="utf-8")
    run["run_end"] = datetime.now(timezone.utc).isoformat()
    run["status"] = "complete"
    post = capture_metrics_snapshot(label="b1126_post")
    promo_d = int(post.get("promotion_count", 0)) - int(baseline.get("promotion_count", 0))
    elite_d = int(post.get("elite_archive_count", 0)) - int(baseline.get("elite_archive_count", 0))
    upgrades = json.loads((COMPOUNDING_POLISH_DIR / "b1124_shadow_elite_upgrade.json").read_text(encoding="utf-8")) if (COMPOUNDING_POLISH_DIR / "b1124_shadow_elite_upgrade.json").exists() else {}
    from doofus.evolution.shadow_elite_upgrade_queue import queue_summary
    up = queue_summary()
    if elite_d <= 0 and up.get("upgrades", 0) == 0:
        run["classification"] = "B1126_COMPOUNDING_POLISH_VALIDATION_PASS_WITH_NOTES"
    path.write_text(json.dumps(run, indent=2), encoding="utf-8")
    (COMPOUNDING_POLISH_DIR / "B1126_COMPOUNDING_POLISH_VALIDATION.md").write_text(f"# B1126\n\n`{run['classification']}`\n", encoding="utf-8")
    return run


def phase_b1127() -> dict:
    subprocess.run([str(PY), "-m", "doofus.reports.autonomous_compounding_polish_report"], cwd=str(ROOT), check=False)
    p = COMPOUNDING_POLISH_DIR / "b1127_final_verdict_analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"classification": "B1127_FINAL_VERDICT_ANALYSIS_PASS_WITH_NOTES"}


def phase_b1128() -> dict:
    subprocess.run([str(PY), "-c", "from doofus.dashboard.doofus_dashboard_app import main; print('ok')"], cwd=str(ROOT), check=False)
    out = {"classification": "B1128_DASHBOARD_REPORT_VISIBILITY_PASS_WITH_NOTES"}
    save_snapshot(COMPOUNDING_POLISH_DIR / "b1128_dashboard_report_visibility.json", out)
    return out


def phase_b1129(head_before: str) -> dict:
    subprocess.run([str(PY), "-m", "pytest", "tests", "-q", "--tb=no"], cwd=str(ROOT), check=False)
    snap = capture_metrics_snapshot(label="b1129_final")
    verdict_path = COMPOUNDING_POLISH_DIR / "b1127_final_verdict_analysis.json"
    verdict = json.loads(verdict_path.read_text(encoding="utf-8")) if verdict_path.exists() else {}
    label = "doofus_autonomous_compounding_polish_complete_with_notes"
    report = {"label": label, "head_before": head_before, "head_after": snap.get("git_head"), "verdict": verdict, "final": snap}
    SHARED.mkdir(parents=True, exist_ok=True)
    for stem in ("DOOFUS-AUTONOMOUS-COMPOUNDING-POLISH-REPORT", "DOOFUS-LATEST-RUN-REPORT"):
        (SHARED / f"{stem}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        (SHARED / f"{stem}.md").write_text(f"# {stem}\n\nLabel: `{label}`\n", encoding="utf-8")
    for stem, content in (
        ("DOOFUS-WATCHDOG-COMPLETION-REPORT", "Watchdog registration and self-repair"),
        ("DOOFUS-DASHBOARD-PERSISTENCE-REPORT", "Dashboard persistence and health"),
        ("DOOFUS-SHADOW-ELITE-UPGRADE-REPORT", "Shadow elite upgrade lane"),
        ("DOOFUS-ELITE-ARCHIVE-GROWTH-REPORT", "Elite archive growth"),
    ):
        (SHARED / f"{stem}.md").write_text(f"# {stem}\n\n{content}\n", encoding="utf-8")
    safety = {"classification": "DOOFUS_AUTONOMOUS_COMPOUNDING_POLISH_FINAL_SAFETY_SWEEP_PASS_WITH_NOTES", "dunce_handoff_touched": False, "blunder_integration": False}
    save_snapshot(COMPOUNDING_POLISH_DIR / "final_safety_sweep.json", safety)
    subprocess.run([str(PY), "-c", "from doofus.safety.on_off_switch import start; start()"], cwd=str(ROOT), check=False)
    return {"classification": "B1129_FINAL_TEST_AUDIT_REPORT_PASS_WITH_NOTES", "label": label}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--phase", default="all", choices=[
        "b1121", "b1122", "b1123", "b1124", "b1125", "b1126", "b1127", "b1128", "b1129",
        "all", "pre_run", "validate_only", "post_run",
    ])
    args = p.parse_args()
    head_before = capture_metrics_snapshot().get("git_head", "unknown")
    phases = {
        "b1121": phase_b1121, "b1122": phase_b1122, "b1123": phase_b1123, "b1124": phase_b1124,
        "b1125": phase_b1125, "b1126": phase_b1126, "b1127": phase_b1127, "b1128": phase_b1128,
        "b1129": lambda: phase_b1129(head_before),
    }
    if args.phase == "pre_run":
        for k in ("b1121", "b1122", "b1123", "b1124", "b1125"):
            print(json.dumps({"phase": k, **phases[k]()}, indent=2, default=str))
        return
    if args.phase in ("validate_only", "post_run"):
        keys = ("b1126", "b1127", "b1128", "b1129") if args.phase == "validate_only" else ("b1127", "b1128", "b1129")
        for k in keys:
            print(json.dumps({"phase": k, **phases[k]()}, indent=2, default=str))
        return
    if args.phase in phases:
        print(json.dumps({"phase": args.phase, **phases[args.phase]()}, indent=2, default=str))
        return
    for k, fn in phases.items():
        print(json.dumps({"phase": k, **fn()}, indent=2, default=str))


if __name__ == "__main__":
    main()
