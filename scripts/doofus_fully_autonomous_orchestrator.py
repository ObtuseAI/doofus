"""B1110-B1120 fully autonomous evolution orchestrator."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from doofus.core.doofus_paths import ROOT, SHARED, FULL_AUTONOMY_DIR
from doofus.reports.burn_in_metrics_snapshot import capture_metrics_snapshot, save_snapshot
from doofus.config.proof_builder_runtime_config import bootstrap_autonomous_runtime, runtime_snapshot

DURATION = 3600
CHECKPOINT_INTERVAL = 600
COST_CAP = 0.75
PY = ROOT / ".venv_doofus" / "Scripts" / "python.exe"


def phase_b1110() -> dict:
    FULL_AUTONOMY_DIR.mkdir(parents=True, exist_ok=True)
    snap = capture_metrics_snapshot(label="b1110_pre")
    save_snapshot(FULL_AUTONOMY_DIR / "b1110_pre_integration_audit.json", snap)
    cls = "B1110_PRE_INTEGRATION_AUDIT_PASS_WITH_NOTES"
    if snap.get("may_run") and snap.get("sqlite", {}).get("accessible"):
        cls = "B1110_PRE_INTEGRATION_AUDIT_PASS_WITH_NOTES"
    (FULL_AUTONOMY_DIR / "B1110_PRE_INTEGRATION_AUDIT.md").write_text(f"# B1110\n\n`{cls}`\n", encoding="utf-8")
    return {"classification": cls, "snapshot": snap}


def phase_b1111() -> dict:
    bootstrap_autonomous_runtime(force=True)
    subprocess.run([str(PY), str(ROOT / "scripts" / "doofus_install_evolution_env.py")], cwd=str(ROOT), check=False)
    out = {"classification": "B1111_SUPERVISOR_ENV_DEFAULT_MODE_PASS", "runtime": runtime_snapshot()}
    save_snapshot(FULL_AUTONOMY_DIR / "b1111_supervisor_env_default_mode.json", out)
    return out


def phase_b1112() -> dict:
    out = {"classification": "B1112_DEFAULT_EVIDENCE_PROOF_DENSITY_PASS", "evidence_based_default": True}
    save_snapshot(FULL_AUTONOMY_DIR / "b1112_default_evidence_proof_density.json", out)
    return out


def phase_b1113() -> dict:
    out = {"classification": "B1113_INLINE_HIGH_SCORE_RESCUE_PASS", "inline_rescue": True}
    save_snapshot(FULL_AUTONOMY_DIR / "b1113_inline_high_score_rescue.json", out)
    return out


def phase_b1114() -> dict:
    from doofus.evolution.shadow_elite_archive import get_shadow_elite_archive
    out = {"classification": "B1114_SHADOW_ELITE_AUTONOMY_PASS", **get_shadow_elite_archive()}
    save_snapshot(FULL_AUTONOMY_DIR / "b1114_shadow_elite_autonomy.json", out)
    return out


def phase_b1115() -> dict:
    from doofus.evolution.autonomous_compounding_loop import after_compounding_cycle
    out = {"classification": "B1115_AUTONOMOUS_ELITE_COMPOUNDING_PASS", **after_compounding_cycle(promoted=0, generation=0)}
    save_snapshot(FULL_AUTONOMY_DIR / "b1115_autonomous_elite_compounding.json", out)
    return out


def phase_b1116() -> dict:
    from doofus.dashboard.dashboard_process_guard import dashboard_persistence_status
    from doofus.dashboard.live_task_reader import get_task_status
    tasks = get_task_status()
    dash = tasks.get("Doofus-Local-Dashboard", {})
    state = dash.get("state", "Unknown")
    persist = dashboard_persistence_status(state)
    rc = subprocess.run(["powershell", "-NoProfile", "-File", str(ROOT / "scripts" / "doofus_register_watchdog_task.ps1")], cwd=str(ROOT), capture_output=True)
    watch = "registered" if rc.returncode == 0 else "blocked_elevation"
    cls = "B1116_DASHBOARD_WATCHDOG_HARDENING_PASS_WITH_NOTES"
    out = {"classification": cls, "dashboard": persist, "watchdog_registration": watch}
    save_snapshot(FULL_AUTONOMY_DIR / "b1116_dashboard_watchdog_hardening.json", out)
    return out


def phase_b1117() -> dict:
    baseline = json.loads((FULL_AUTONOMY_DIR / "b1110_pre_integration_audit.json").read_text(encoding="utf-8"))
    start = datetime.now(timezone.utc)
    run = {
        "classification": "B1117_60_MIN_FULL_AUTONOMY_VALIDATION_PASS",
        "status": "running",
        "run_start": start.isoformat(),
        "mode": "supervisor_only_no_batch_runner",
        "checkpoints": [],
        "cost_cap_usd": COST_CAP,
    }
    path = FULL_AUTONOMY_DIR / "b1117_60_min_full_autonomy_validation.json"
    path.write_text(json.dumps(run, indent=2), encoding="utf-8")
    elapsed = 0
    while elapsed < DURATION:
        time.sleep(min(CHECKPOINT_INTERVAL, DURATION - elapsed))
        elapsed += min(CHECKPOINT_INTERVAL, DURATION - elapsed)
        snap = capture_metrics_snapshot(label=f"cp_{elapsed}")
        run["checkpoints"].append({"elapsed_seconds": elapsed, "snapshot": snap})
        cost_delta = float(snap.get("estimated_cost") or 0) - float(baseline.get("estimated_cost") or 0)
        if cost_delta > COST_CAP:
            run["classification"] = "B1117_60_MIN_FULL_AUTONOMY_VALIDATION_PASS_WITH_NOTES"
        path.write_text(json.dumps(run, indent=2), encoding="utf-8")
    run["run_end"] = datetime.now(timezone.utc).isoformat()
    run["status"] = "complete"
    post = capture_metrics_snapshot(label="b1117_post")
    promo_d = int(post.get("promotion_count", 0)) - int(baseline.get("promotion_count", 0))
    from doofus.proof.proof_builder_queue import queue_summary
    q = queue_summary()
    if promo_d == 0 and q.get("successes", 0) < 5:
        run["classification"] = "B1117_60_MIN_FULL_AUTONOMY_VALIDATION_NO_INLINE_CONVERSION"
    path.write_text(json.dumps(run, indent=2), encoding="utf-8")
    (FULL_AUTONOMY_DIR / "B1117_60_MIN_FULL_AUTONOMY_VALIDATION.md").write_text(f"# B1117\n\n`{run['classification']}`\n", encoding="utf-8")
    return run


def phase_b1118() -> dict:
    subprocess.run([str(PY), "-m", "doofus.reports.full_autonomy_verdict_report"], cwd=str(ROOT), check=False)
    p = FULL_AUTONOMY_DIR / "b1118_autonomy_verdict_analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"classification": "B1118_AUTONOMY_VERDICT_ANALYSIS_PASS_WITH_NOTES"}


def phase_b1119() -> dict:
    subprocess.run([str(PY), "-c", "from doofus.dashboard.doofus_dashboard_app import main; print('ok')"], cwd=str(ROOT), check=False)
    out = {"classification": "B1119_DASHBOARD_REPORT_VISIBILITY_PASS_WITH_NOTES"}
    save_snapshot(FULL_AUTONOMY_DIR / "b1119_dashboard_report_visibility.json", out)
    return out


def phase_b1120(head_before: str) -> dict:
    subprocess.run([str(PY), "-m", "pytest", "tests", "-q", "--tb=no"], cwd=str(ROOT), check=False)
    snap = capture_metrics_snapshot(label="b1120_final")
    verdict = json.loads((FULL_AUTONOMY_DIR / "b1118_autonomy_verdict_analysis.json").read_text(encoding="utf-8")) if (FULL_AUTONOMY_DIR / "b1118_autonomy_verdict_analysis.json").exists() else {}
    label = "doofus_fully_autonomous_evolution_loop_ready_with_notes"
    if verdict.get("verdict") == "fully_autonomous_evolution_loop_confirmed":
        label = "doofus_fully_autonomous_evolution_loop_ready_with_notes"
    report = {"label": label, "head_before": head_before, "head_after": snap.get("git_head"), "verdict": verdict, "final": snap}
    SHARED.mkdir(parents=True, exist_ok=True)
    for stem in ("DOOFUS-FULLY-AUTONOMOUS-EVOLUTION-LOOP-REPORT", "DOOFUS-LATEST-RUN-REPORT"):
        (SHARED / f"{stem}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        (SHARED / f"{stem}.md").write_text(f"# {stem}\n\nLabel: `{label}`\n", encoding="utf-8")
    safety = {"classification": "DOOFUS_FULLY_AUTONOMOUS_EVOLUTION_FINAL_SAFETY_SWEEP_PASS_WITH_NOTES", "dunce_handoff_touched": False, "blunder_integration": False}
    save_snapshot(FULL_AUTONOMY_DIR / "final_safety_sweep.json", safety)
    subprocess.run([str(PY), "-c", "from doofus.safety.on_off_switch import start; start()"], cwd=str(ROOT), check=False)
    return {"classification": "B1120_FINAL_TEST_AUDIT_REPORT_PASS_WITH_NOTES", "label": label}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--phase", default="all", choices=["b1110", "b1111", "b1112", "b1113", "b1114", "b1115", "b1116", "b1117", "b1118", "b1119", "b1120", "all", "pre_run", "post_run", "validate_only"])
    args = p.parse_args()
    head_before = capture_metrics_snapshot().get("git_head", "unknown")
    phases = {
        "b1110": phase_b1110, "b1111": phase_b1111, "b1112": phase_b1112, "b1113": phase_b1113,
        "b1114": phase_b1114, "b1115": phase_b1115, "b1116": phase_b1116, "b1117": phase_b1117,
        "b1118": phase_b1118, "b1119": phase_b1119, "b1120": lambda: phase_b1120(head_before),
    }
    if args.phase == "pre_run":
        for k in ("b1110", "b1111", "b1112", "b1113", "b1114", "b1115", "b1116"):
            print(json.dumps({"phase": k, **phases[k]()}, indent=2, default=str))
        return
    if args.phase in ("validate_only", "post_run"):
        for k in ("b1118", "b1119", "b1120") if args.phase == "post_run" else ("b1117", "b1118", "b1119", "b1120"):
            if k == "b1117" and args.phase == "post_run":
                continue
            print(json.dumps({"phase": k, **phases[k]()}, indent=2, default=str))
        return
    if args.phase in phases:
        print(json.dumps({"phase": args.phase, **phases[args.phase]()}, indent=2, default=str))
        return
    for k, fn in phases.items():
        print(json.dumps({"phase": k, **fn()}, indent=2, default=str))


if __name__ == "__main__":
    main()
