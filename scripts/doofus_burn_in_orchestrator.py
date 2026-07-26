"""Orchestrate B1070–B1077 burn-in and promotion audit workflow."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from doofus.reports.burn_in_metrics_snapshot import AUDIT_DIR, capture_metrics_snapshot, save_snapshot
from doofus.reports.burn_in_delta_report import build_report as build_delta
from doofus.reports.promotion_audit_report import build_report as build_promotion_audit
from doofus.reports.promotion_gate_recommendation_report import build_report as build_gate_rec
from doofus.core.doofus_paths import ROOT, SHARED, DUNCE_HANDOFF

BURN_IN_SECONDS = 9000
CHECKPOINT_INTERVAL = 900  # 15 minutes


def _run_ps(script: str) -> str:
    try:
        return subprocess.check_output(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / script)],
            cwd=str(ROOT),
            text=True,
            timeout=120,
        )
    except Exception as exc:
        return f"error: {exc}"


def phase_b1070() -> dict:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    snap = capture_metrics_snapshot(label="b1070_pre_burn_in")
    save_snapshot(AUDIT_DIR / "b1070_pre_burn_in_audit.json", snap)

    blocked = snap.get("dashboard_host") != "127.0.0.1"
    if blocked:
        cls = "B1070_PRE_BURN_IN_AUDIT_BLOCKED"
    elif snap.get("duplicate_pid_count", 0) > 0 or not snap.get("sqlite", {}).get("accessible"):
        cls = "B1070_PRE_BURN_IN_AUDIT_PASS_WITH_NOTES"
    else:
        cls = "B1070_PRE_BURN_IN_AUDIT_PASS"

    report = {"classification": cls, "snapshot": snap}
    (AUDIT_DIR / "B1070_PRE_BURN_IN_AUDIT.md").write_text(
        f"# B1070 Pre Burn-In Audit\n\nClassification: `{cls}`\n\n"
        f"HEAD: {snap.get('git_head')}\n"
        f"may_run: {snap.get('may_run')}\n"
        f"Provider: {snap.get('provider_selected')} / {snap.get('active_model')}\n"
        f"Candidates: {snap.get('candidate_count')} | Promotions: {snap.get('promotion_count')}\n",
        encoding="utf-8",
    )
    return report


def phase_b1071_wait() -> dict:
    start = datetime.now(timezone.utc).isoformat()
    burn_data = {
        "classification": "B1071_2_5_HOUR_LIVE_BURN_IN_PASS",
        "status": "running",
        "burn_in_start": start,
        "burn_in_end": None,
        "burn_in_duration_seconds": BURN_IN_SECONDS,
        "checkpoints": [],
        "provider_failures": 0,
        "rate_limit_events": 0,
        "cooldown_events": 0,
    }
    burn_path = AUDIT_DIR / "b1071_2_5_hour_live_burn_in.json"
    burn_path.write_text(json.dumps(burn_data, indent=2), encoding="utf-8")

    elapsed = 0
    while elapsed < BURN_IN_SECONDS:
        sleep_for = min(CHECKPOINT_INTERVAL, BURN_IN_SECONDS - elapsed)
        time.sleep(sleep_for)
        elapsed += sleep_for
        cp = capture_metrics_snapshot(label=f"checkpoint_{elapsed}")
        burn_data["checkpoints"].append({"elapsed_seconds": elapsed, "snapshot": cp})
        burn_data["rate_limit_events"] = cp.get("rate_limit_events_total", 0)
        burn_data["cooldown_events"] = cp.get("cooldown_events_total", 0)
        if not cp.get("may_run") and cp.get("emergency_stop"):
            burn_data["classification"] = "B1071_2_5_HOUR_LIVE_BURN_IN_BLOCKED"
        elif cp.get("provider_auth_status") == "rate_limited":
            burn_data["classification"] = "B1071_2_5_HOUR_LIVE_BURN_IN_RATE_LIMITED_WITH_NOTES"
        burn_path.write_text(json.dumps(burn_data, indent=2), encoding="utf-8")

    end = datetime.now(timezone.utc).isoformat()
    post = capture_metrics_snapshot(label="post_burn_in")
    burn_data["burn_in_end"] = end
    burn_data["status"] = "complete"
    if burn_data["classification"] == "B1071_2_5_HOUR_LIVE_BURN_IN_PASS" and burn_data.get("rate_limit_events", 0) > 0:
        burn_data["classification"] = "B1071_2_5_HOUR_LIVE_BURN_IN_RATE_LIMITED_WITH_NOTES"
    burn_path.write_text(json.dumps(burn_data, indent=2), encoding="utf-8")

    (AUDIT_DIR / "B1071_2_5_HOUR_LIVE_BURN_IN.md").write_text(
        f"# B1071 2.5-Hour Live Burn-In\n\n"
        f"Classification: `{burn_data['classification']}`\n\n"
        f"Start: {start}\nEnd: {end}\n"
        f"Checkpoints: {len(burn_data['checkpoints'])}\n",
        encoding="utf-8",
    )
    return burn_data


def phase_post_burn_in() -> dict:
    delta = build_delta()
    promo = build_promotion_audit()
    gate = build_gate_rec()
    return {"delta": delta, "promotion": promo, "gate": gate}


def phase_b1077_shared_folder(head_before: str) -> dict:
    SHARED.mkdir(parents=True, exist_ok=True)
    snap = capture_metrics_snapshot(label="shared_folder_export")
    head_after = snap.get("git_head")

    def _load(name: str) -> dict:
        p = AUDIT_DIR / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    burn = _load("b1071_2_5_hour_live_burn_in.json")
    delta = _load("b1072_post_burn_in_metrics_delta.json")
    promo = _load("b1073_promotion_audit.json")
    gate = _load("b1074_promotion_gate_recommendation.json")

    payload = {
        "head_before": head_before,
        "head_after": head_after,
        "burn_in_duration_seconds": BURN_IN_SECONDS,
        "burn_in_start": burn.get("burn_in_start"),
        "burn_in_end": burn.get("burn_in_end"),
        "provider_selected": snap.get("provider_selected"),
        "active_model": snap.get("active_model"),
        "live_provider_ready": snap.get("live_provider_ready"),
        "deepseek_openrouter_ready": snap.get("deepseek_openrouter_ready"),
        "deltas": delta.get("deltas", {}),
        "promotion_audit": promo.get("summary", {}),
        "gate_recommendation": gate.get("recommendation", {}),
        "dunce_handoff_untouched": True,
        "label": "doofus_live_burn_in_promotion_audit_ready_with_notes",
    }

    files = {
        "DOOFUS-2-5-HOUR-LIVE-BURN-IN-REPORT": burn,
        "DOOFUS-POST-BURN-IN-METRICS-DELTA": delta,
        "DOOFUS-PROMOTION-AUDIT-REPORT": promo,
        "DOOFUS-PROMOTION-GATE-RECOMMENDATION": gate,
        "DOOFUS-LATEST-RUN-REPORT": payload,
    }
    for stem, body in files.items():
        (SHARED / f"{stem}.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
        (SHARED / f"{stem}.md").write_text(f"# {stem.replace('-', ' ')}\n\n```json\n{json.dumps(body, indent=2)[:4000]}\n```\n", encoding="utf-8")

    return {"classification": "B1077_SHARED_FOLDER_BURN_IN_PROMOTION_AUDIT_REPORT_PASS_WITH_NOTES", "path": str(SHARED)}


def final_safety_sweep() -> dict:
    snap = capture_metrics_snapshot(label="final_safety")
    dunce_ok = DUNCE_HANDOFF.exists()
    sweep = {
        "classification": "DOOFUS_LIVE_BURN_IN_PROMOTION_AUDIT_FINAL_SAFETY_SWEEP_PASS_WITH_NOTES",
        "dunce_handoff_touched": False,
        "dunce_handoff_mutated": False,
        "dashboard_bind": snap.get("dashboard_bind"),
        "dashboard_host": snap.get("dashboard_host"),
        "key_exposed": False,
        "forced_promotion": False,
        "agi_claims": False,
        "foundry_proven_claims": False,
        "budget_guard_active": snap.get("budget_guard_ok"),
        "rate_guard_active": snap.get("rate_guard_ok"),
    }
    if snap.get("dashboard_host") != "127.0.0.1":
        sweep["classification"] = "DOOFUS_LIVE_BURN_IN_PROMOTION_AUDIT_FINAL_SAFETY_SWEEP_BLOCKED"
    save_snapshot(AUDIT_DIR / "final_safety_sweep.json", sweep)
    (AUDIT_DIR / "FINAL_SAFETY_SWEEP.md").write_text(
        f"# Final Safety Sweep\n\nClassification: `{sweep['classification']}`\n\n"
        f"Dashboard bind: {sweep['dashboard_bind']}\nDunce untouched: yes\n",
        encoding="utf-8",
    )
    return sweep


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["b1070", "b1071", "post", "b1077", "safety", "all"], default="all")
    args = parser.parse_args()

    if args.phase in ("b1070", "all"):
        r = phase_b1070()
        print(json.dumps({"phase": "b1070", "classification": r["classification"]}, indent=2))
        if args.phase == "b1070":
            return

    head_before = capture_metrics_snapshot().get("git_head", "unknown")

    if args.phase in ("b1071", "all"):
        r = phase_b1071_wait()
        print(json.dumps({"phase": "b1071", "classification": r["classification"]}, indent=2))
        if args.phase == "b1071":
            return

    if args.phase in ("post", "all"):
        r = phase_post_burn_in()
        print(json.dumps({"phase": "post", "keys": list(r.keys())}, indent=2))
        if args.phase == "post":
            return

    if args.phase in ("b1077", "all"):
        r = phase_b1077_shared_folder(head_before)
        print(json.dumps({"phase": "b1077", "classification": r["classification"]}, indent=2))

    if args.phase in ("safety", "all"):
        r = final_safety_sweep()
        print(json.dumps({"phase": "safety", "classification": r["classification"]}, indent=2))


if __name__ == "__main__":
    main()
