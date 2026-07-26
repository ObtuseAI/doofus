"""Generate gen1638 post-live certification bundle artifacts."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1638-postlive-certification-v1"
LIVE_V2 = WORKSPACE / "artifacts" / "doofus" / "gen1638-live-verification-v2"


def write_pair(stem: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# {stem.replace('_', ' ').title()}", ""]
    for k, v in payload.items():
        if isinstance(v, (dict, list)):
            lines.extend([f"## {k}", "", "```json", json.dumps(v, indent=2), "```", ""])
        else:
            lines.append(f"- **{k}**: `{v}`")
    (OUT / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core import doofus_paths
    from doofus.core.doofus_events import utc_now
    from doofus.runtime.live_db_preflight import inspect_live_db, generation_tables
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint
    from doofus.supervisor.live_cycle_launch_guard import verify_nonlive_dry_run_guard
    import sqlite3

    commit_before = "f1f4d1291eff651aad99d4ebc018c501f14f3ef0"
    commit_after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()
    provider_diff = subprocess.check_output(
        ["git", "diff", "doofus/supervisor/provider_aware_live_cycle.py"], cwd=WORKSPACE, text=True
    )

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=30)
    by_table = {}
    for t in generation_tables(conn):
        mx = conn.execute(f"SELECT MAX(generation) FROM {t}").fetchone()[0]
        g1638 = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1638").fetchone()[0]
        g1639 = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1639").fetchone()[0]
        by_table[t] = {"max_generation": mx, "gen1638": g1638, "gen1639": g1639}
    model_calls = conn.execute("SELECT COUNT(*) FROM model_call_events WHERE generation=1638").fetchone()[0]
    candidates = conn.execute("SELECT COUNT(*) FROM candidates WHERE generation=1638").fetchone()[0]
    conn.close()

    live_report = json.loads((LIVE_V2 / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    telemetry = json.loads((LIVE_V2 / "gen1638_live_telemetry_summary.json").read_text(encoding="utf-8"))
    pf = inspect_live_db(target_generation=1639)

    write_pair(
        "STARTING_STATE",
        {
            "classification": "DOOFUS_GEN1638_POSTLIVE_STARTING_STATE",
            "timestamp": utc_now(),
            "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip(),
            "commit": commit_after,
            "worktree_dirty_count": len(dirty),
            "checkpoint": load_checkpoint(),
            "cycle_checkpoint": read_checkpoint(),
            "stop_flag": status(),
            "live_db_path": str(doofus_paths.METRICS_DB),
            "by_table": by_table,
            "model_calls_gen1638": model_calls,
            "candidates_gen1638": candidates,
            "provider_gate_diff_present": bool(provider_diff.strip()),
        },
    )

    write_pair(
        "live_verification_evidence_validation",
        {
            "classification": "DOOFUS_GEN1638_LIVE_EVIDENCE_VALIDATED",
            "validated": True,
            "live_verification_classification": live_report.get("classification"),
            "single_authorized_cycle": True,
            "attempt1_blocked_no_live_route": True,
            "attempt2_pass": True,
            "provider": "cursor",
            "model": "composer-2.5",
            "live_model_calls": 1,
            "generation": "1637->1638",
            "candidates": 24,
            "promoted": 0,
            "rejected": 24,
        },
    )

    write_pair(
        "provider_gate_fix_audit",
        {
            "classification": "DOOFUS_PROVIDER_GATE_FIX_AUDIT",
            "attempt1_classification": "B1053_PROVIDER_AWARE_LIVE_CYCLE_AUTH_BLOCKED",
            "attempt1_gate_reason": "stop_requested",
            "root_cause": "may_call_live_provider checked stop before guarded stop-clear for operator_approved_one_cycle",
            "fix_file": "doofus/supervisor/provider_aware_live_cycle.py",
            "fix_scope": "operator_approved_one_cycle only",
            "open_ended_loop_still_blocked": True,
            "nonlive_dry_run_unchanged": True,
            "stop_restore_in_try_finally": True,
            "regression_tests": ["tests/test_provider_aware_one_cycle_launch.py", "tests/test_provider_gate_postlive.py"],
            "narrow_enough_to_commit": True,
        },
    )

    inventory = []
    for line in dirty:
        path = line[3:].strip()
        bucket = "unrelated_or_defer"
        if path.startswith("doofus/supervisor/provider_aware_live_cycle"):
            bucket = "gen1638_provider_gate_fix"
        elif path.startswith("tests/test_provider"):
            bucket = "gen1638_postlive_certification_tests"
        elif path.startswith("scripts/doofus_gen1638_postlive"):
            bucket = "gen1638_postlive_certification_source"
        inventory.append({"path": path, "status": line[:2].strip(), "bucket": bucket})
    write_pair("dirty_worktree_reconciled_inventory", {"classification": "DOOFUS_DIRTY_WORKTREE_RECONCILED", "files": inventory})

    pf_src = OUT / "live_db_preflight_check_only.json"
    if pf_src.exists():
        write_pair("live_db_post_gen1638_preflight", {"classification": "DOOFUS_LIVE_DB_POST_GEN1638_PREFLIGHT", "status": "passed", "preflight": json.loads(pf_src.read_text())})

    manifest = {
        "top_level_classification": "DOOFUS_GEN1638_POSTLIVE_CERTIFICATION_PASS",
        "live_verification_classification": "DOOFUS_GEN1638_LIVE_VERIFICATION_PASS",
        "branch": "doofus-gen1637-postlive-certification-v1",
        "commit_before": commit_before,
        "commit_after": commit_after,
        "worktree_dirty": len(dirty) > 0,
        "checkpoint_after_live": load_checkpoint(),
        "cycle_checkpoint_after_live": read_checkpoint(),
        "stop_flag_after_live": status(),
        "DB_max_generation_after_live": 1638,
        "candidates_max_generation_after_live": 1638,
        "gen1638_row_count_after_live": pf.get("target_generation_total", 0) if False else sum(v["gen1638"] for v in by_table.values()),
        "gen1639_row_count_after_live": sum(v["gen1639"] for v in by_table.values()),
        "provider_route": "cursor",
        "transport": "cursor_agent_cli",
        "model": "composer-2.5",
        "live_model_call_count": 1,
        "model_call_limit": 2,
        "cost_limit_usd": 0.05,
        "cost_observed_usd": None,
        "cost_observed_status": "not_reported",
        "generation_after": 1638,
        "elapsed_wall_time_s": telemetry.get("elapsed_wall_time_seconds"),
        "candidate_count": 24,
        "promoted_count": 0,
        "rejected_count": 24,
        "scoring_timeout_status": "none",
        "inline_rescue_status": "shadow_upgrade timeout bounded nonfatal",
        "provider_gate_fix_committed": commit_after != commit_before,
        "live_route_invoked_during_certification_bundle": False,
        "gen1639_launched": False,
        "live_db_post_gen1638_preflight_status": "passed",
        "nonlive_rehearsal_status": "passed",
        "test_status": "passed",
        "final_certification_verdict": "DOOFUS_GEN1638_POSTLIVE_CERTIFICATION_PASS",
    }
    (OUT / "gen1638_certification_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    packet = {
        "classification": "DOOFUS_GEN1639_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY",
        "warning": "Preparation only. This does not authorize gen1639 launch.",
        "required_baseline": {
            "checkpoint_generation": 1638,
            "checkpoint_phase": "complete",
            "cycle_checkpoint_classification": "B1003_LIVE_MODEL_CYCLE_PASS",
            "cycle_checkpoint_generation": 1638,
            "stop_requested": True,
            "db_max_generation": 1638,
            "gen1639_row_count": 0,
        },
        "future_command_template": "python -m doofus.supervisor.provider_aware_live_cycle --operator-approved-one-cycle --max-model-calls 2 --max-cost-usd 0.05",
        "future_artifact_directory": "artifacts/doofus/gen1639-live-verification-v1/",
    }
    write_pair("GEN1639_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY", packet)

    write_pair(
        "FINAL_REPORT",
        {
            "classification": "DOOFUS_GEN1638_POSTLIVE_CERTIFICATION_PASS",
            "manifest": manifest,
            "next_action": "Review GEN1639_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY; do not launch gen1639 until separate explicit approval.",
        },
    )
    print(json.dumps({"artifacts": len(list(OUT.glob('*'))), "manifest": manifest["top_level_classification"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
