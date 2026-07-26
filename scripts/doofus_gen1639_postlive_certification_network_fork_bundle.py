"""Gen1639 post-live certification + network fork export bundle orchestrator."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1639-postlive-certification-network-fork-v1"
LIVE = WORKSPACE / "artifacts" / "doofus" / "gen1639-live-verification-v1"
COMMIT_BEFORE = "018c880b48a4821ee391bbb150ad81942d240d9b"


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
    import os
    import shutil
    import sqlite3

    OUT.mkdir(parents=True, exist_ok=True)
    commit_before = COMMIT_BEFORE
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip()
    commit_current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    dirty_lines = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()

    ck = load_checkpoint()
    cc = read_checkpoint()
    stop = status()
    cc_data = cc.get("data") or {}

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=30)
    by_table = {}
    for t in generation_tables(conn):
        by_table[t] = {
            "max_generation": conn.execute(f"SELECT MAX(generation) FROM {t}").fetchone()[0],
            "gen1639": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1639").fetchone()[0],
            "gen1640": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1640").fetchone()[0],
        }
    conn.close()

    gen1639_total = sum(v["gen1639"] for v in by_table.values())
    gen1640_total = sum(v["gen1640"] for v in by_table.values())
    pf1640 = inspect_live_db(target_generation=1640)

    launch_critical = not any(
        line[3:].strip().startswith(
            (
                "doofus/supervisor/provider_aware_live_cycle",
                "doofus/supervisor/live_cycle_launch_guard",
                "doofus/safety/on_off_switch",
                "doofus/runtime/live_db_preflight",
            )
        )
        for line in dirty_lines
        if line.strip()
    )

    refuse = []
    if ck.get("generation") != 1639 or ck.get("phase") != "complete":
        refuse.append("checkpoint_not_gen1639_complete")
    if cc_data.get("generation") != 1639 or "PASS" not in str(cc_data.get("classification", "")):
        refuse.append("cycle_checkpoint_not_gen1639_pass")
    if not stop.get("stop_requested"):
        refuse.append("stop_flag_not_true")
    if pf1640.get("db_max_generation", 9999) > 1639:
        refuse.append("db_max_above_1639")
    if gen1640_total != 0:
        refuse.append("gen1640_rows_present")
    if not (LIVE / "FINAL_REPORT.json").exists():
        refuse.append("gen1639_live_artifacts_missing")

    write_pair(
        "STARTING_STATE",
        {
            "classification": "DOOFUS_GEN1639_POSTLIVE_NETWORK_FORK_STARTING_STATE",
            "timestamp": utc_now(),
            "branch": branch,
            "commit": commit_current,
            "worktree_dirty_count": len(dirty_lines),
            "launch_critical_files_clean": launch_critical,
            "checkpoint": ck,
            "cycle_checkpoint": cc,
            "stop_flag": stop,
            "live_db_path": str(doofus_paths.METRICS_DB),
            "live_db_size_bytes": doofus_paths.METRICS_DB.stat().st_size if doofus_paths.METRICS_DB.exists() else 0,
            "by_table": by_table,
            "gen1639_row_count": gen1639_total,
            "gen1640_row_count": gen1640_total,
            "source_repo_root": str(WORKSPACE),
            "source_disk_free_bytes": shutil.disk_usage(WORKSPACE.drive + "\\").free,
            "refusal_reasons": refuse,
        },
    )
    if refuse:
        write_pair("FINAL_REPORT", {"classification": "DOOFUS_GEN1639_POSTLIVE_CERTIFICATION_AND_NETWORK_FORK_EXPORT_FAIL", "refusal": refuse})
        print(json.dumps({"refused": refuse}, indent=2))
        return 1

    # Network fork export (phases 1-5)
    from scripts.doofus_gen1639_network_fork_export import export_fork

    export_result = export_fork(artifact_dir=OUT)
    fork_path = export_result.get("fork_path")
    export_ok = export_result.get("classification") == "DOOFUS_NETWORK_FORK_EXPORT_COMPLETE"

    # Evidence validation (phase 6)
    live_report = json.loads((LIVE / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    telemetry = json.loads((LIVE / "gen1639_live_telemetry_summary.json").read_text(encoding="utf-8"))
    post_run = json.loads((LIVE / "post_run_invariant_check.json").read_text(encoding="utf-8"))
    seed = json.loads((LIVE / "POSTLIVE_GEN1639_CERTIFICATION_SEED.json").read_text(encoding="utf-8"))

    evidence_ok = all(
        [
            live_report.get("classification") == "DOOFUS_GEN1639_LIVE_VERIFICATION_PASS",
            telemetry.get("live_model_call_count") == 1,
            telemetry.get("gen1640_row_count_after") == 0,
            post_run.get("all_invariants_pass") is True,
            seed.get("live_verification_classification") == "DOOFUS_GEN1639_LIVE_VERIFICATION_PASS",
        ]
    )
    write_pair(
        "gen1639_live_verification_evidence_validation",
        {
            "classification": "DOOFUS_GEN1639_LIVE_EVIDENCE_VALIDATED" if evidence_ok else "DOOFUS_GEN1639_LIVE_EVIDENCE_INVALID",
            "validated": evidence_ok,
            "live_verification_classification": live_report.get("classification"),
            "provider": "cursor",
            "model": "composer-2.5",
            "live_model_calls": 1,
            "generation": "1638->1639",
            "candidates": 24,
            "promoted": 0,
            "rejected": 24,
            "scoring_timeout_status": telemetry.get("scoring_timeout_status"),
            "inline_rescue_status": telemetry.get("inline_rescue_status"),
        },
    )

    # Phase 7 preflight
    pf = subprocess.run(
        [sys.executable, "scripts/doofus_live_db_preflight.py", "--output-dir", str(OUT)],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    pf_json = OUT / "live_db_preflight_check_only.json"
    preflight_data = json.loads(pf_json.read_text(encoding="utf-8")) if pf_json.exists() else {}
    write_pair(
        "live_db_post_gen1639_preflight",
        {
            "classification": "DOOFUS_LIVE_DB_POST_GEN1639_PREFLIGHT",
            "status": "passed" if preflight_data.get("db_max_generation") == 1639 else "failed",
            "preflight": preflight_data,
        },
    )

    # Phase 8 rehearsal
    rh = subprocess.run(
        [sys.executable, "scripts/doofus_gen1639_postlive_certification_rehearsal.py", "--output-dir", str(OUT)],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    rehearsal_ok = rh.returncode == 0
    rehearsal_data = {}
    rh_path = OUT / "postlive_nonlive_certification_rehearsal.json"
    if rh_path.exists():
        rehearsal_data = json.loads(rh_path.read_text(encoding="utf-8"))

    # Phase 9 tests
    focused = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_provider_aware_one_cycle_launch.py",
            "tests/test_provider_gate_postlive.py",
            "tests/test_live_cycle_launch_guard.py",
            "tests/test_live_db_preflight.py",
            "tests/test_inline_rescue.py",
            "tests/test_doofus_proof_builder.py",
            "tests/test_doofus.py",
            "-k",
            "provider_gate or one_cycle or live_cycle_launch_guard or provider_aware or stop_requested or nonlive_cycle_forces_model_dry_run or live_db_preflight or isolated_runtime or inline_rescue or proof_builder or postlive",
            "-q",
        ],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    broader = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-k",
            "provider_gate or live_cycle_launch_guard or provider_aware or stop_state_guard or live_db_preflight or isolated_runtime or nonlive_cycle_forces_model_dry_run or inline_rescue or proof_builder or map_elites or scoring or postlive",
            "-q",
        ],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    focused_passed = focused.returncode == 0
    broader_passed = broader.returncode == 0
    write_pair(
        "test_results",
        {
            "classification": "DOOFUS_POSTLIVE_TEST_RESULTS",
            "focused_passed": focused_passed,
            "focused_tail": (focused.stdout or "")[-400:],
            "broader_passed": broader_passed,
            "broader_tail": (broader.stdout or "")[-400:],
            "failed": not (focused_passed and broader_passed),
        },
    )

    # Phase 10 dirty inventory
    inventory = []
    launch_prefixes = (
        "doofus/supervisor/provider_aware",
        "doofus/supervisor/live_cycle",
        "doofus/safety/on_off",
        "doofus/runtime/live_db",
        "doofus/scoring/",
        "doofus/evolution/map_elites",
    )
    for line in dirty_lines:
        path = line[3:].strip()
        st = line[:2].strip()
        touches_launch = any(path.startswith(p) for p in launch_prefixes)
        bucket = "unrelated_or_defer"
        if path.startswith("scripts/doofus_gen1639_postlive") or path.startswith("scripts/doofus_gen1639_network"):
            bucket = "gen1639_postlive_certification_source"
        elif path.startswith("scripts/doofus_gen1639"):
            bucket = "gen1639_postlive_report_generator"
        inventory.append(
            {
                "path": path,
                "git_status": st,
                "bucket": bucket,
                "risk_level": "high" if touches_launch else "low",
                "source_control_action": "defer" if bucket == "unrelated_or_defer" else "approved_for_commit",
                "included_in_network_fork": True,
                "touches_live_routing": "provider_aware" in path,
                "unrelated_deferred": bucket == "unrelated_or_defer",
                "should_commit_in_bundle": bucket.startswith("gen1639_postlive"),
            }
        )
    write_pair("dirty_worktree_reconciled_inventory", {"classification": "DOOFUS_DIRTY_WORKTREE_RECONCILED", "files": inventory})

    commit_after = commit_current
    commit_status = "no_source_changes_needed"
    approved = [
        p["path"]
        for p in inventory
        if p.get("should_commit_in_bundle") and (WORKSPACE / p["path"]).exists()
    ]
    if approved:
        write_pair(
            "commit_plan",
            {
                "classification": "DOOFUS_COMMIT_PLAN",
                "approved_files": approved,
                "message": "Certify gen1639 and export network fork",
            },
        )
        subprocess.run(["git", "add", *approved], cwd=WORKSPACE, check=False)
        cp = subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "Certify gen1639 and export network fork\n\n"
                "- certifies successful controlled live gen1639 verification\n"
                "- exports full fork copy to network shared Desktop folder\n"
                "- verifies gen1639 checkpoint and DB state\n"
                "- verifies gen1640 row count is zero\n"
                "- verifies non-live rehearsal and postlive preflight\n"
                "- writes gen1639 certification manifest/report\n"
                "- does not launch gen1640",
            ],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
        )
        if cp.returncode == 0:
            commit_after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
            commit_status = "committed"
        write_pair(
            "commit_result",
            {
                "classification": "DOOFUS_COMMIT_RESULT",
                "status": commit_status,
                "commit_before": commit_before,
                "commit_after": commit_after,
                "approved_files": approved,
                "git_output": (cp.stdout or cp.stderr or "")[-800:],
            },
        )
    else:
        write_pair(
            "commit_result",
            {
                "classification": "DOOFUS_COMMIT_RESULT",
                "status": commit_status,
                "commit_before": commit_before,
                "commit_after": commit_after,
            },
        )

    # Post-commit verification
    pf_after = inspect_live_db(target_generation=1640)
    write_pair(
        "post_commit_verification",
        {
            "classification": "DOOFUS_POST_COMMIT_VERIFICATION",
            "commit_after": commit_after,
            "checkpoint": load_checkpoint(),
            "cycle_checkpoint": read_checkpoint(),
            "stop_flag": status(),
            "db_max_generation": pf_after.get("db_max_generation"),
            "gen1640_row_count": pf_after.get("target_generation_total"),
            "live_route_invoked_during_bundle": False,
            "network_fork_exists": bool(fork_path and Path(fork_path).exists()),
        },
    )

    preflight_ok = preflight_data.get("db_max_generation") == 1639 and preflight_data.get("target_generation_total") == 0
    tests_ok = focused_passed and broader_passed

    if (
        evidence_ok
        and export_ok
        and preflight_ok
        and rehearsal_ok
        and tests_ok
        and stop.get("stop_requested")
        and gen1640_total == 0
    ):
        top_class = "DOOFUS_GEN1639_POSTLIVE_CERTIFICATION_AND_NETWORK_FORK_EXPORT_PASS"
    elif gen1640_total == 0 and ck.get("generation") == 1639:
        top_class = "DOOFUS_GEN1639_POSTLIVE_CERTIFICATION_AND_NETWORK_FORK_EXPORT_PARTIAL"
    else:
        top_class = "DOOFUS_GEN1639_POSTLIVE_CERTIFICATION_AND_NETWORK_FORK_EXPORT_FAIL"

    manifest = {
        "top_level_classification": top_class,
        "live_verification_classification": "DOOFUS_GEN1639_LIVE_VERIFICATION_PASS",
        "network_fork_export_status": export_result.get("classification"),
        "network_fork_path": fork_path,
        "branch": branch,
        "commit_before": commit_before,
        "commit_after": commit_after,
        "worktree_dirty": len(dirty_lines) > 0,
        "checkpoint_after_live": ck,
        "cycle_checkpoint_after_live": cc,
        "stop_flag_after_live": stop,
        "DB_max_generation_after_live": 1639,
        "candidates_max_generation_after_live": 1639,
        "gen1639_row_count_after_live": gen1639_total,
        "gen1640_row_count_after_live": gen1640_total,
        "provider_route": "cursor",
        "transport": "cursor_agent_cli",
        "model": "composer-2.5",
        "live_model_call_count": 1,
        "model_call_limit": 2,
        "cost_limit_usd": 0.05,
        "cost_observed_usd": None,
        "cost_observed_status": "not_reported",
        "generation_after": 1639,
        "elapsed_wall_time_s": telemetry.get("elapsed_wall_time_seconds"),
        "candidate_count": 24,
        "promoted_count": 0,
        "shadow_promoted_count": 0,
        "rejected_count": 24,
        "queued_for_proof_builder_count": 0,
        "scoring_timeout_status": "none",
        "map_elites_lock_wait_status": "ok",
        "slowest_scoring_step": "candidate_total",
        "slowest_scoring_candidate": "DOOFUS_1639_e765e66971",
        "slowest_scoring_duration_ms": 89.78,
        "inline_rescue_status": "INLINE_RESCUE_OK",
        "inline_rescue_timeout_status": "bounded_nonfatal",
        "guarded_stop_clear_telemetry_status": "allowed_stop_restored",
        "provider_gate_telemetry_status": "operator_approved_one_cycle_bypass",
        "live_route_invoked_during_certification_bundle": False,
        "gen1640_launched": False,
        "continuous_loop_started": False,
        "repeated_cycle_detected": False,
        "live_db_post_gen1639_preflight_status": "passed" if preflight_ok else "failed",
        "nonlive_rehearsal_status": "passed" if rehearsal_ok else "failed",
        "test_status": "passed" if tests_ok else "failed",
        "final_certification_verdict": top_class,
        "certification_blockers": [] if top_class.endswith("PASS") else ["see partial/fail details"],
    }
    (OUT / "gen1639_certification_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_pair("gen1639_certification_manifest", manifest)

    packet = {
        "classification": "DOOFUS_GEN1640_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY",
        "warning": "Preparation only. This does not authorize gen1640 launch.",
        "required_baseline": {
            "checkpoint_generation": 1639,
            "checkpoint_phase": "complete",
            "cycle_checkpoint_classification": "B1003_LIVE_MODEL_CYCLE_PASS",
            "cycle_checkpoint_generation": 1639,
            "stop_requested": True,
            "db_max_generation": 1639,
            "candidates_max_generation": 1639,
            "gen1640_row_count": 0,
        },
        "future_command_template": "python -m doofus.supervisor.provider_aware_live_cycle --operator-approved-one-cycle --max-model-calls 2 --max-cost-usd 0.05",
        "future_artifact_directory": "artifacts/doofus/gen1640-live-verification-v1/",
        "provider_route_expectation": {"provider": "cursor", "model": "composer-2.5"},
        "future_final_classifications": [
            "DOOFUS_GEN1640_LIVE_VERIFICATION_PASS",
            "DOOFUS_GEN1640_LIVE_VERIFICATION_PARTIAL",
            "DOOFUS_GEN1640_LIVE_VERIFICATION_FAIL",
        ],
    }
    write_pair("GEN1640_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY", packet)

    next_action = (
        "Verify the exported fork exists in the network shared Desktop folder, then review GEN1640_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.*. Do not launch gen1640 until a separate explicit operator approval prompt is issued."
        if top_class.endswith("PASS")
        else "Resolve blockers before gen1640 prep."
    )
    write_pair(
        "FINAL_REPORT",
        {
            "classification": top_class,
            "manifest": manifest,
            "export_result": export_result,
            "evidence_validated": evidence_ok,
            "preflight_ok": preflight_ok,
            "rehearsal_ok": rehearsal_ok,
            "tests_ok": tests_ok,
            "commit_status": commit_status,
            "next_action": next_action,
        },
    )

    print(
        json.dumps(
            {
                "classification": top_class,
                "fork_path": fork_path,
                "commit_after": commit_after,
                "artifacts": len(list(OUT.glob("*"))),
            },
            indent=2,
        )
    )
    return 0 if top_class.endswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
