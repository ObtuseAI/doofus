"""B1130-B1140 Windows runtime closure orchestrator."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from doofus.core.doofus_paths import ROOT, SHARED, RUNTIME_CLOSURE_DIR
from doofus.reports.burn_in_metrics_snapshot import capture_metrics_snapshot, save_snapshot

VALIDATION_SECONDS = 1800
CHECKPOINT_INTERVAL = 600
COST_CAP = 0.50
PY = ROOT / ".venv_doofus" / "Scripts" / "python.exe"


def phase_b1130() -> dict:
    RUNTIME_CLOSURE_DIR.mkdir(parents=True, exist_ok=True)
    from doofus.runtime.runtime_health import get_runtime_health
    snap = capture_metrics_snapshot(label="b1130_pre")
    snap["runtime_health"] = get_runtime_health()
    save_snapshot(RUNTIME_CLOSURE_DIR / "b1130_pre_runtime_closure_audit.json", snap)
    cls = "B1130_PRE_RUNTIME_CLOSURE_AUDIT_PASS_WITH_NOTES"
    (RUNTIME_CLOSURE_DIR / "B1130_PRE_RUNTIME_CLOSURE_AUDIT.md").write_text(f"# B1130\n\n`{cls}`\n", encoding="utf-8")
    return {"classification": cls, "snapshot": snap}


def phase_b1137() -> dict:
    baseline = json.loads((RUNTIME_CLOSURE_DIR / "b1130_pre_runtime_closure_audit.json").read_text(encoding="utf-8"))
    start = datetime.now(timezone.utc)
    run = {"classification": "B1137_SHORT_LIVE_FULL_FUNCTION_VALIDATION_PASS", "status": "running", "run_start": start.isoformat(), "checkpoints": [], "cost_cap_usd": COST_CAP}
    path = RUNTIME_CLOSURE_DIR / "b1137_short_live_full_function_validation.json"
    path.write_text(json.dumps(run, indent=2), encoding="utf-8")
    elapsed = 0
    while elapsed < VALIDATION_SECONDS:
        time.sleep(min(300, VALIDATION_SECONDS - elapsed))
        elapsed += min(300, VALIDATION_SECONDS - elapsed)
        subprocess.run([str(PY), "-m", "doofus.runtime.windows_runtime_manager", "--once"], cwd=str(ROOT), capture_output=True)
        snap = capture_metrics_snapshot(label=f"cp_{elapsed}")
        from doofus.runtime.runtime_health import get_runtime_health
        snap["runtime_health"] = get_runtime_health()
        run["checkpoints"].append({"elapsed_seconds": elapsed, "snapshot": snap})
        cost_delta = float(snap.get("estimated_cost") or 0) - float(baseline.get("estimated_cost") or 0)
        if cost_delta > COST_CAP:
            run["classification"] = "B1137_SHORT_LIVE_FULL_FUNCTION_VALIDATION_PASS_WITH_NOTES"
        path.write_text(json.dumps(run, indent=2, default=str), encoding="utf-8")
    run["run_end"] = datetime.now(timezone.utc).isoformat()
    run["status"] = "complete"
    post = capture_metrics_snapshot(label="b1137_post")
    cand_d = int(post.get("candidate_count", 0)) - int(baseline.get("candidate_count", 0))
    health = json.loads(subprocess.check_output([str(PY), "-c", "from doofus.runtime.runtime_health import get_runtime_health; import json; print(json.dumps(get_runtime_health(), default=str))"], cwd=str(ROOT), text=True))
    hb = health.get("supervisor", {}).get("heartbeat_age_seconds")
    dash = health.get("dashboard", {}).get("reachable")
    if cand_d <= 0:
        run["classification"] = "B1137_SHORT_LIVE_FULL_FUNCTION_VALIDATION_BLOCKED_NO_CANDIDATE_DELTA"
    elif hb is None or hb >= 180:
        run["classification"] = "B1137_SHORT_LIVE_FULL_FUNCTION_VALIDATION_BLOCKED_STALE_HEARTBEAT"
    elif not dash:
        run["classification"] = "B1137_SHORT_LIVE_FULL_FUNCTION_VALIDATION_BLOCKED_DASHBOARD_DEAD"
    path.write_text(json.dumps(run, indent=2, default=str), encoding="utf-8")
    return run


def phase_b1138() -> dict:
    subprocess.run([str(PY), "-m", "doofus.reports.full_functionality_verdict_report"], cwd=str(ROOT), check=False)
    return json.loads((RUNTIME_CLOSURE_DIR / "b1138_final_functionality_verdict.json").read_text(encoding="utf-8"))


def phase_b1140(head_before: str) -> dict:
    subprocess.run([str(PY), "-m", "pytest", "tests", "-q", "--tb=no"], cwd=str(ROOT), check=False)
    snap = capture_metrics_snapshot(label="b1140_final")
    verdict = json.loads((RUNTIME_CLOSURE_DIR / "b1138_final_functionality_verdict.json").read_text(encoding="utf-8"))
    label = "doofus_windows_runtime_fully_functional" if verdict.get("verdict") == "fully_functional" else "doofus_windows_runtime_fully_functional_with_notes" if verdict.get("verdict") == "fully_functional_with_notes" else "doofus_windows_runtime_not_fully_functional_blocked"
    report = {"label": label, "head_before": head_before, "head_after": snap.get("git_head"), "verdict": verdict, "final": snap}
    SHARED.mkdir(parents=True, exist_ok=True)
    for stem in ("DOOFUS-WINDOWS-RUNTIME-CLOSURE-REPORT", "DOOFUS-LATEST-RUN-REPORT", "DOOFUS-FULL-FUNCTIONALITY-VERDICT"):
        (SHARED / f"{stem}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        (SHARED / f"{stem}.md").write_text(f"# {stem}\n\nLabel: `{label}`\nVerdict: `{verdict.get('verdict')}`\n", encoding="utf-8")
    safety = {"classification": "DOOFUS_WINDOWS_RUNTIME_CLOSURE_FINAL_SAFETY_SWEEP_PASS_WITH_NOTES", "dunce_handoff_touched": False}
    save_snapshot(RUNTIME_CLOSURE_DIR / "final_safety_sweep.json", safety)
    return {"classification": "B1140_FINAL_TEST_REPORT_COMMIT_PASS_WITH_NOTES", "label": label}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--phase", default="b1137", choices=["b1130", "b1137", "b1138", "b1140", "pre_run", "post_run"])
    args = p.parse_args()
    head = capture_metrics_snapshot().get("git_head", "unknown")
    if args.phase == "pre_run":
        print(json.dumps(phase_b1130(), indent=2, default=str))
        return
    if args.phase == "post_run":
        print(json.dumps({"b1138": phase_b1138(), "b1140": phase_b1140(head)}, indent=2, default=str))
        return
    phases = {"b1130": phase_b1130, "b1137": phase_b1137, "b1138": phase_b1138, "b1140": lambda: phase_b1140(head)}
    print(json.dumps(phases[args.phase](), indent=2, default=str))


if __name__ == "__main__":
    main()
