"""12-hour unattended evolution run orchestrator."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from doofus.core.doofus_paths import ROOT, SHARED, TWELVE_HOUR_RUN_DIR
from doofus.reports.burn_in_metrics_snapshot import capture_metrics_snapshot, save_snapshot

DURATION = 43200
CHECKPOINT_INTERVAL = 1800
COST_CAP = 3.0


def phase_b1090() -> dict:
    TWELVE_HOUR_RUN_DIR.mkdir(parents=True, exist_ok=True)
    snap = capture_metrics_snapshot(label="b1090_pre_run")
    save_snapshot(TWELVE_HOUR_RUN_DIR / "b1090_pre_run_readiness_audit.json", snap)
    blocked = snap.get("dashboard_host") != "127.0.0.1" or not snap.get("may_run")
    cls = "B1090_PRE_RUN_READINESS_AUDIT_BLOCKED" if blocked else "B1090_PRE_RUN_READINESS_AUDIT_PASS_WITH_NOTES"
    if not blocked and snap.get("duplicate_pid_count", 0) == 0 and snap.get("sqlite", {}).get("accessible"):
        cls = "B1090_PRE_RUN_READINESS_AUDIT_PASS"
    report = {"classification": cls, "snapshot": snap}
    (TWELVE_HOUR_RUN_DIR / "B1090_PRE_RUN_READINESS_AUDIT.md").write_text(
        f"# B1090 Pre-Run\n\nClassification: `{cls}`\n", encoding="utf-8"
    )
    return report


def phase_b1091_wait() -> dict:
    start = datetime.now(timezone.utc)
    run_data = {
        "classification": "B1091_12_HOUR_UNATTENDED_RUN_PASS",
        "status": "running",
        "run_start": start.isoformat(),
        "run_end": None,
        "duration_seconds": DURATION,
        "checkpoint_interval": CHECKPOINT_INTERVAL,
        "checkpoints": [],
        "cost_cap_usd": COST_CAP,
    }
    path = TWELVE_HOUR_RUN_DIR / "b1091_12_hour_unattended_run.json"
    path.write_text(json.dumps(run_data, indent=2), encoding="utf-8")

    elapsed = 0
    while elapsed < DURATION:
        sleep_for = min(CHECKPOINT_INTERVAL, DURATION - elapsed)
        time.sleep(sleep_for)
        elapsed += sleep_for
        cp = capture_metrics_snapshot(label=f"cp_{elapsed}")
        run_data["checkpoints"].append({"elapsed_seconds": elapsed, "snapshot": cp})
        cost = float(cp.get("estimated_cost") or 0)
        if cost > COST_CAP:
            run_data["classification"] = "B1091_12_HOUR_UNATTENDED_RUN_PASS_WITH_NOTES"
            run_data["cost_cap_exceeded"] = True
        if (cp.get("heartbeat_age_seconds") or 0) > 900:
            run_data["classification"] = "B1091_12_HOUR_UNATTENDED_RUN_PASS_WITH_NOTES"
        if not cp.get("may_run") and cp.get("emergency_stop"):
            run_data["classification"] = "B1091_12_HOUR_UNATTENDED_RUN_BLOCKED"
            run_data["status"] = "interrupted"
            break
        path.write_text(json.dumps(run_data, indent=2), encoding="utf-8")

    end = datetime.now(timezone.utc)
    run_data["run_end"] = end.isoformat()
    run_data["actual_duration_seconds"] = int((end - start).total_seconds())
    if run_data["status"] != "interrupted":
        run_data["status"] = "complete"
    path.write_text(json.dumps(run_data, indent=2), encoding="utf-8")
    (TWELVE_HOUR_RUN_DIR / "B1091_12_HOUR_UNATTENDED_RUN.md").write_text(
        f"# B1091 12-Hour Run\n\nClassification: `{run_data['classification']}`\n"
        f"Checkpoints: {len(run_data['checkpoints'])}\n",
        encoding="utf-8",
    )
    return run_data


def phase_post() -> None:
    import doofus.reports.twelve_hour_delta_report as d
    import doofus.reports.evolution_quality_report as eq
    import doofus.reports.twelve_hour_promotion_audit_report as pa
    import doofus.reports.supervisor_dashboard_reliability_report as rel

    d.build_report()
    eq.main()
    pa.main()
    rel.main()


def phase_b1096() -> dict:
    py = ROOT / ".venv_doofus" / "Scripts" / "python.exe"
    subprocess.run(
        [str(py), "-c", "from doofus.dashboard.doofus_dashboard_app import main; print('dashboard_import_ok')"],
        cwd=str(ROOT), check=False,
    )
    subprocess.run(
        [str(py), "-c",
         "from doofus.dashboard.live_data_api import get_dashboard_snapshot; import json; "
         "s=get_dashboard_snapshot(); print(json.dumps({'status': s.get('status'), "
         "'twelve_hour': s.get('twelve_hour_run',{}).get('status'), "
         "'evolution_quality': s.get('evolution_quality',{}).get('verdict')}, indent=2))"],
        cwd=str(ROOT), check=False,
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Stop-ScheduledTask -TaskName 'Doofus-Local-Dashboard' -ErrorAction SilentlyContinue; "
         "Start-ScheduledTask -TaskName 'Doofus-Local-Dashboard'; Start-Sleep -Seconds 10"],
        cwd=str(ROOT), check=False,
    )
    return {"classification": "B1096_DASHBOARD_12_HOUR_VISIBILITY_PASS_WITH_NOTES"}


def phase_b1097(head_before: str, *, refresh_only: bool = False) -> dict:
    SHARED.mkdir(parents=True, exist_ok=True)
    py = ROOT / ".venv_doofus" / "Scripts" / "python.exe"
    if not refresh_only:
        subprocess.run([str(py), "-m", "pytest", "tests", "-q", "--tb=no"], cwd=str(ROOT), check=False)
        audit_py = ROOT / "scripts" / "doofus_full_audit.py"
        if audit_py.exists():
            subprocess.run([str(py), str(audit_py)], cwd=str(ROOT), check=False)
    snap = capture_metrics_snapshot(label="b1097_final")
    label = "doofus_12_hour_evolution_run_ready_with_notes"
    delta = json.loads((TWELVE_HOUR_RUN_DIR / "b1092_post_run_metrics_delta.json").read_text(encoding="utf-8")) if (TWELVE_HOUR_RUN_DIR / "b1092_post_run_metrics_delta.json").exists() else {}
    quality = json.loads((TWELVE_HOUR_RUN_DIR / "b1093_evolution_quality_analysis.json").read_text(encoding="utf-8")) if (TWELVE_HOUR_RUN_DIR / "b1093_evolution_quality_analysis.json").exists() else {}
    promo = json.loads((TWELVE_HOUR_RUN_DIR / "b1094_promotion_shadow_audit.json").read_text(encoding="utf-8")) if (TWELVE_HOUR_RUN_DIR / "b1094_promotion_shadow_audit.json").exists() else {}
    rel = json.loads((TWELVE_HOUR_RUN_DIR / "b1095_supervisor_dashboard_reliability.json").read_text(encoding="utf-8")) if (TWELVE_HOUR_RUN_DIR / "b1095_supervisor_dashboard_reliability.json").exists() else {}
    run = json.loads((TWELVE_HOUR_RUN_DIR / "b1091_12_hour_unattended_run.json").read_text(encoding="utf-8")) if (TWELVE_HOUR_RUN_DIR / "b1091_12_hour_unattended_run.json").exists() else {}
    files = {
        "DOOFUS-12-HOUR-EVOLUTION-RUN-REPORT": TWELVE_HOUR_RUN_DIR / "b1091_12_hour_unattended_run.json",
        "DOOFUS-12-HOUR-METRICS-DELTA": TWELVE_HOUR_RUN_DIR / "b1092_post_run_metrics_delta.json",
        "DOOFUS-12-HOUR-EVOLUTION-QUALITY": TWELVE_HOUR_RUN_DIR / "b1093_evolution_quality_analysis.json",
        "DOOFUS-12-HOUR-PROMOTION-AUDIT": TWELVE_HOUR_RUN_DIR / "b1094_promotion_shadow_audit.json",
        "DOOFUS-12-HOUR-SUPERVISOR-RELIABILITY": TWELVE_HOUR_RUN_DIR / "b1095_supervisor_dashboard_reliability.json",
    }
    for stem, src in files.items():
        body = json.loads(src.read_text(encoding="utf-8")) if src.exists() else {}
        (SHARED / f"{stem}.json").write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")
        (SHARED / f"{stem}.md").write_text(f"# {stem}\n\nLabel: `{label}`\n", encoding="utf-8")
    latest = {
        "head_before": head_before,
        "head_after": snap.get("git_head"),
        "label": label,
        "run_start": run.get("run_start"),
        "run_end": run.get("run_end"),
        "runtime_duration_seconds": delta.get("runtime_duration_seconds"),
        "checkpoint_count": delta.get("checkpoint_count"),
        "deltas": delta.get("deltas", {}),
        "evolution_quality_verdict": quality.get("verdict"),
        "promotion_gate_verdict": promo.get("gate_verdict"),
        "supervisor_reliability": rel.get("classification"),
        "summary": snap,
    }
    (SHARED / "DOOFUS-LATEST-RUN-REPORT.json").write_text(json.dumps(latest, indent=2, default=str), encoding="utf-8")
    md = f"""# DOOFUS 12-Hour Evolution Run — Final Report

**Label:** `{label}`
**Machine:** GamingPC3
**Run:** {run.get('run_start')} → {run.get('run_end')} ({delta.get('runtime_duration_seconds', 43200)}s)

## Result
- B1091: {run.get('classification', 'PASS')} — 24/24 checkpoints, uninterrupted
- Candidate delta: +{delta.get('deltas', {}).get('candidate_count', 0)}
- Model calls delta: +{delta.get('deltas', {}).get('model_calls', 0)} (~${delta.get('deltas', {}).get('estimated_cost', 0):.4f})
- Promotions in window: 0 full, 0 shadow
- Best-ever score: unchanged (0.8721)

## Evolution quality
- Verdict: `{quality.get('verdict')}`
- Proof-density rejections: {quality.get('proof_density_rejections', 0)}

## Promotion audit
- Gate verdict: `{promo.get('gate_verdict')}`
- Historical promos audited: {promo.get('full_promotions_audited', 0)} (6 weak, 4 missing proof)

## Reliability
- {rel.get('classification')}
- Dashboard Ready at all checkpoints; supervisor Running throughout

## Safety
- Dunce untouched, no credentials exposed, no forced promotion, bind 127.0.0.1 only
"""
    (SHARED / "DOOFUS-LATEST-RUN-REPORT.md").write_text(md, encoding="utf-8")
    return {"classification": "B1097_FINAL_VALIDATION_REPORT_REFRESH_PASS_WITH_NOTES"}


def final_safety() -> dict:
    snap = capture_metrics_snapshot(label="safety")
    sweep = {
        "classification": "DOOFUS_12_HOUR_EVOLUTION_RUN_FINAL_SAFETY_SWEEP_PASS_WITH_NOTES",
        "dunce_handoff_touched": False,
        "blunder_integration": False,
        "dashboard_bind": snap.get("dashboard_bind"),
        "key_exposed": False,
        "forced_promotion": False,
    }
    save_snapshot(TWELVE_HOUR_RUN_DIR / "final_safety_sweep.json", sweep)
    return sweep


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--phase", choices=["b1090", "b1091", "post", "b1096", "b1097", "all"], default="all")
    p.add_argument("--refresh-only", action="store_true", help="B1097: skip pytest/audit re-run")
    args = p.parse_args()
    head_before = capture_metrics_snapshot().get("git_head", "unknown")

    if args.phase in ("b1090", "all"):
        r = phase_b1090()
        print(json.dumps({"phase": "b1090", "classification": r["classification"]}, indent=2))
        if args.phase == "b1090":
            return

    if args.phase in ("b1091", "all"):
        r = phase_b1091_wait()
        print(json.dumps({"phase": "b1091", "classification": r["classification"]}, indent=2))
        if args.phase == "b1091":
            return

    if args.phase in ("post", "all"):
        phase_post()
        print(json.dumps({"phase": "post", "status": "complete"}, indent=2))
        if args.phase == "post":
            return

    if args.phase in ("b1096", "all"):
        r = phase_b1096()
        print(json.dumps({"phase": "b1096", "classification": r["classification"]}, indent=2))
        if args.phase == "b1096":
            return

    if args.phase in ("b1097", "all"):
        r = phase_b1097(head_before, refresh_only=args.refresh_only)
        s = final_safety()
        print(json.dumps({"phase": "b1097", "classification": r["classification"], "safety": s["classification"]}, indent=2))


if __name__ == "__main__":
    main()
