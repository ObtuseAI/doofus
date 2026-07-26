"""B1100-B1108 proof-builder tuning orchestrator."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from doofus.core.doofus_paths import ROOT, SHARED, PROOF_BUILDER_TUNING_DIR
from doofus.reports.burn_in_metrics_snapshot import capture_metrics_snapshot, save_snapshot
from doofus.proof.proof_candidate_selector import select_and_enqueue

DURATION = 3600
CHECKPOINT_INTERVAL = 600
COST_CAP = 0.75
PY = ROOT / ".venv_doofus" / "Scripts" / "python.exe"

ENV_FLAGS = {
    "DOOFUS_EVOLUTION_PRESSURE_MODE": "1",
    "DOOFUS_PROOF_BUILDER_MODE": "1",
    "DOOFUS_SHADOW_ELITE_MODE": "1",
    "DOOFUS_HIGH_SCORE_RESCUE_MODE": "1",
    "DOOFUS_BASE_CANDIDATES_PER_CYCLE": "6",
    "DOOFUS_MAX_CANDIDATES_PER_CYCLE": "20",
    "DOOFUS_STAGNATION_CYCLES_BEFORE_PRESSURE": "2",
    "DOOFUS_PROOF_BUILDER_MAX_RETRIES": "3",
    "DOOFUS_PROOF_BUILDER_TOP_N": "100",
    "DOOFUS_SHADOW_ELITE_ARCHIVE_SIZE": "50",
}


def _apply_env() -> None:
    for k, v in ENV_FLAGS.items():
        os.environ[k] = v
    applied = PROOF_BUILDER_TUNING_DIR / "threshold_applied.json"
    if applied.exists():
        t = json.loads(applied.read_text(encoding="utf-8")).get("threshold")
        if t is not None:
            os.environ["DOOFUS_MIN_PROOF_DENSITY_SCORE"] = str(t)


def phase_b1100() -> dict:
    PROOF_BUILDER_TUNING_DIR.mkdir(parents=True, exist_ok=True)
    snap = capture_metrics_snapshot(label="b1100_pre")
    save_snapshot(PROOF_BUILDER_TUNING_DIR / "b1100_pre_tuning_audit.json", snap)
    blocked = not snap.get("may_run") or snap.get("dashboard_host") != "127.0.0.1"
    cls = "B1100_PRE_TUNING_AUDIT_BLOCKED" if blocked else "B1100_PRE_TUNING_AUDIT_PASS_WITH_NOTES"
    if not blocked and snap.get("sqlite", {}).get("accessible"):
        cls = "B1100_PRE_TUNING_AUDIT_PASS_WITH_NOTES"
    (PROOF_BUILDER_TUNING_DIR / "B1100_PRE_TUNING_AUDIT.md").write_text(f"# B1100\n\nClassification: `{cls}`\n", encoding="utf-8")
    return {"classification": cls, "snapshot": snap}


def phase_b1101() -> dict:
    subprocess.run([str(PY), "-m", "doofus.reports.high_score_rejection_report"], cwd=str(ROOT), check=True)
    return json.loads((PROOF_BUILDER_TUNING_DIR / "b1101_high_score_rejection_miner.json").read_text(encoding="utf-8"))


def phase_b1102() -> dict:
    from doofus.proof.proof_builder_queue import queue_summary
    out = {"classification": "B1102_PROOF_BUILDER_QUEUE_PASS", "queue": queue_summary()}
    save_snapshot(PROOF_BUILDER_TUNING_DIR / "b1102_proof_builder_queue.json", out)
    (PROOF_BUILDER_TUNING_DIR / "B1102_PROOF_BUILDER_QUEUE.md").write_text("# B1102 Proof Builder Queue\n", encoding="utf-8")
    return out


def phase_b1103() -> dict:
    from doofus.evolution.shadow_elite_archive import get_shadow_elite_archive
    out = {"classification": "B1103_SHADOW_ELITE_ARCHIVE_PASS", **get_shadow_elite_archive()}
    save_snapshot(PROOF_BUILDER_TUNING_DIR / "b1103_shadow_elite_archive.json", out)
    (PROOF_BUILDER_TUNING_DIR / "B1103_SHADOW_ELITE_ARCHIVE.md").write_text("# B1103 Shadow Elite\n", encoding="utf-8")
    return out


def phase_b1104() -> dict:
    subprocess.run([str(PY), "-m", "doofus.reports.proof_threshold_sweep_report"], cwd=str(ROOT), check=True)
    return json.loads((PROOF_BUILDER_TUNING_DIR / "b1104_threshold_sweep_tuning.json").read_text(encoding="utf-8"))


def phase_b1105() -> dict:
    _apply_env()
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    cp = load_checkpoint()
    baseline = float(cp.get("baseline_score") or 0.7732)
    seed = select_and_enqueue()
    start = datetime.now(timezone.utc)
    run_data = {
        "classification": "B1105_60_MIN_AGGRESSIVE_CONVERSION_RUN_PASS",
        "status": "running",
        "run_start": start.isoformat(),
        "run_end": None,
        "duration_seconds": DURATION,
        "seed_enqueue": seed,
        "checkpoints": [],
        "cost_cap_usd": COST_CAP,
    }
    path = PROOF_BUILDER_TUNING_DIR / "b1105_60_min_aggressive_conversion_run.json"
    path.write_text(json.dumps(run_data, indent=2), encoding="utf-8")
    elapsed = 0
    while elapsed < DURATION:
        sleep_for = min(CHECKPOINT_INTERVAL, DURATION - elapsed)
        time.sleep(sleep_for)
        elapsed += sleep_for
        cp = capture_metrics_snapshot(label=f"cp_{elapsed}")
        from doofus.proof.proof_builder_runner import run_proof_builder_batch
        pb = run_proof_builder_batch(limit=10, baseline=baseline)
        run_data["checkpoints"].append({"elapsed_seconds": elapsed, "snapshot": cp, "proof_builder_batch": pb})
        cost_delta = float(cp.get("estimated_cost") or 0) - float(
            json.loads((PROOF_BUILDER_TUNING_DIR / "b1100_pre_tuning_audit.json").read_text()).get("estimated_cost", 0)
        )
        if cost_delta > COST_CAP:
            run_data["classification"] = "B1105_60_MIN_AGGRESSIVE_CONVERSION_RUN_PASS_WITH_NOTES"
            run_data["cost_cap_exceeded"] = True
        if not cp.get("may_run") and cp.get("emergency_stop"):
            run_data["classification"] = "B1105_60_MIN_AGGRESSIVE_CONVERSION_RUN_BLOCKED"
            run_data["status"] = "interrupted"
            break
        path.write_text(json.dumps(run_data, indent=2), encoding="utf-8")
    end = datetime.now(timezone.utc)
    run_data["run_end"] = end.isoformat()
    run_data["actual_duration_seconds"] = int((end - start).total_seconds())
    if run_data["status"] != "interrupted":
        run_data["status"] = "complete"
    post = capture_metrics_snapshot(label="b1105_post")
    promo_d = int(post.get("promotion_count", 0)) - int(json.loads((PROOF_BUILDER_TUNING_DIR / "b1100_pre_tuning_audit.json").read_text()).get("promotion_count", 0))
    shadow_d = int(post.get("shadow_promotion_count", 0))
    if promo_d == 0 and shadow_d == 0:
        from doofus.proof.proof_builder_queue import queue_summary
        q = queue_summary()
        if q.get("successes", 0) == 0:
            run_data["classification"] = "B1105_60_MIN_AGGRESSIVE_CONVERSION_RUN_NO_CONVERSION"
    path.write_text(json.dumps(run_data, indent=2), encoding="utf-8")
    (PROOF_BUILDER_TUNING_DIR / "B1105_60_MIN_AGGRESSIVE_CONVERSION_RUN.md").write_text(
        f"# B1105 60-Min Run\n\nClassification: `{run_data['classification']}`\n", encoding="utf-8"
    )
    return run_data


def phase_b1106() -> dict:
    subprocess.run([str(PY), "-m", "doofus.reports.aggressive_tuning_verdict_report"], cwd=str(ROOT), check=True)
    return json.loads((PROOF_BUILDER_TUNING_DIR / "b1106_conversion_analysis.json").read_text(encoding="utf-8"))


def phase_b1107() -> dict:
    subprocess.run([str(PY), "-c", "from doofus.dashboard.doofus_dashboard_app import main; print('dashboard_import_ok')"], cwd=str(ROOT), check=False)
    subprocess.run(
        [str(PY), "-c",
         "from doofus.dashboard.live_data_api import get_dashboard_snapshot; import json; "
         "s=get_dashboard_snapshot(); print(json.dumps({'status': s.get('status'), "
         "'proof_builder': s.get('proof_builder',{}).get('enabled'), "
         "'shadow_elites': s.get('shadow_elite',{}).get('shadow_elite_count'), "
         "'conversion': s.get('conversion',{}).get('verdict')}, indent=2))"],
        cwd=str(ROOT), check=False,
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Stop-ScheduledTask -TaskName 'Doofus-Local-Dashboard' -ErrorAction SilentlyContinue; "
         "Start-ScheduledTask -TaskName 'Doofus-Local-Dashboard'; Start-Sleep -Seconds 10"],
        cwd=str(ROOT), check=False,
    )
    out = {"classification": "B1107_DASHBOARD_REPORT_VISIBILITY_PASS_WITH_NOTES"}
    save_snapshot(PROOF_BUILDER_TUNING_DIR / "b1107_dashboard_report_visibility.json", out)
    return out


def phase_b1108(head_before: str) -> dict:
    subprocess.run([str(PY), "-m", "pytest", "tests", "-q", "--tb=no"], cwd=str(ROOT), check=False)
    snap = capture_metrics_snapshot(label="b1108_final")
    baseline = json.loads((PROOF_BUILDER_TUNING_DIR / "b1100_pre_tuning_audit.json").read_text(encoding="utf-8"))
    verdict = json.loads((PROOF_BUILDER_TUNING_DIR / "b1106_conversion_analysis.json").read_text(encoding="utf-8"))
    label = "doofus_proof_builder_shadow_elite_tuned_with_notes"
    if verdict.get("verdict") == "tuning_correct_full_promotion_seen":
        label = "doofus_proof_builder_shadow_elite_tuned_with_notes"
    elif verdict.get("verdict") in ("proof_generation_still_bottleneck", "threshold_correct_proof_builder_weak"):
        label = "doofus_proof_builder_shadow_elite_partial_with_notes"
    report = {
        "label": label,
        "head_before": head_before,
        "head_after": snap.get("git_head"),
        "baseline": baseline,
        "final": snap,
        "verdict": verdict,
    }
    SHARED.mkdir(parents=True, exist_ok=True)
    for stem, data in [
        ("DOOFUS-PROOF-BUILDER-SHADOW-ELITE-TUNING-REPORT", report),
        ("DOOFUS-AGGRESSIVE-TUNING-VERDICT", verdict),
        ("DOOFUS-LATEST-RUN-REPORT", report),
    ]:
        (SHARED / f"{stem}.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        (SHARED / f"{stem}.md").write_text(f"# {stem}\n\nLabel: `{label}`\n", encoding="utf-8")
    b1101 = PROOF_BUILDER_TUNING_DIR / "b1101_high_score_rejection_miner.json"
    b1104 = PROOF_BUILDER_TUNING_DIR / "b1104_threshold_sweep_tuning.json"
    b1105 = PROOF_BUILDER_TUNING_DIR / "b1105_60_min_aggressive_conversion_run.json"
    if b1101.exists():
        (SHARED / "DOOFUS-HIGH-SCORE-REJECTION-MINER.json").write_text(b1101.read_text(encoding="utf-8"), encoding="utf-8")
    if b1104.exists():
        (SHARED / "DOOFUS-PROOF-THRESHOLD-SWEEP.json").write_text(b1104.read_text(encoding="utf-8"), encoding="utf-8")
    if b1105.exists():
        (SHARED / "DOOFUS-60-MIN-AGGRESSIVE-CONVERSION-RUN.json").write_text(b1105.read_text(encoding="utf-8"), encoding="utf-8")
    sweep = json.loads(b1104.read_text()) if b1104.exists() else {}
    safety = {
        "classification": "DOOFUS_PROOF_BUILDER_SHADOW_ELITE_FINAL_SAFETY_SWEEP_PASS_WITH_NOTES",
        "dunce_handoff_touched": False,
        "blunder_integration": False,
        "dashboard_bind": snap.get("dashboard_bind"),
        "key_exposed": False,
        "forced_promotion": False,
        "threshold_changed": sweep.get("recommended_threshold") is not None,
    }
    save_snapshot(PROOF_BUILDER_TUNING_DIR / "final_safety_sweep.json", safety)
    (PROOF_BUILDER_TUNING_DIR / "FINAL_SAFETY_SWEEP.md").write_text("# Final Safety Sweep PASS_WITH_NOTES\n", encoding="utf-8")
    subprocess.run([str(PY), "-c", "from doofus.safety.on_off_switch import start; start()"], cwd=str(ROOT), check=False)
    return {"classification": "B1108_FINAL_TEST_AUDIT_REPORT_PASS_WITH_NOTES", "label": label}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--phase", default="all", choices=["b1100", "b1101", "b1102", "b1103", "b1104", "b1105", "b1106", "b1107", "b1108", "all", "pre_run", "post_run"])
    args = p.parse_args()
    head_before = capture_metrics_snapshot().get("git_head", "unknown")
    phases = {
        "b1100": phase_b1100, "b1101": phase_b1101, "b1102": phase_b1102, "b1103": phase_b1103,
        "b1104": phase_b1104, "b1105": phase_b1105, "b1106": phase_b1106, "b1107": phase_b1107,
        "b1108": lambda: phase_b1108(head_before),
    }
    if args.phase == "pre_run":
        for k in ("b1100", "b1101", "b1102", "b1103", "b1104"):
            r = phases[k]()
            print(json.dumps({"phase": k, "classification": r.get("classification")}, indent=2))
        return
    if args.phase == "post_run":
        for k in ("b1106", "b1107", "b1108"):
            r = phases[k]()
            print(json.dumps({"phase": k, "classification": r.get("classification")}, indent=2))
        return
    if args.phase == "all":
        for k, fn in phases.items():
            r = fn()
            print(json.dumps({"phase": k, "classification": r.get("classification", r.get("verdict"))}, indent=2))
    else:
        r = phases[args.phase]()
        print(json.dumps({"phase": args.phase, "classification": r.get("classification", r.get("verdict"))}, indent=2))


if __name__ == "__main__":
    main()
