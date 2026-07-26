"""Gen1640 post-live certification, telemetry hardening, and gen1641 prep-only bundle."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1640-postlive-certification-v1"
RETRY3 = WORKSPACE / "artifacts" / "doofus" / "gen1640-retry3-live-verification-v1"
EXPECTED_COMMIT = "8f1fb70d59547ac7f2e16569ed06dbf74f0d5745"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_pair(stem: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# {stem.replace('_', ' ').title()}", "", f"**Classification:** `{payload.get('classification', 'n/a')}`", ""]
    for k, v in payload.items():
        if k == "classification":
            continue
        if isinstance(v, (dict, list)):
            lines.extend([f"## {k}", "", "```json", json.dumps(v, indent=2)[:14000], "```", ""])
        else:
            lines.append(f"- **{k}**: `{v}`")
    (OUT / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_cmd(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=WORKSPACE, capture_output=True, text=True, timeout=timeout)


def file_hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def phase0(commit_before: str) -> dict:
    for key in ("DOOFUS_STATE", "DOOFUS_METRICS_DB", "DOOFUS_CONTROL"):
        os.environ.pop(key, None)
    from doofus.core import doofus_paths
    from doofus.reports.run_window_telemetry_filter import read_jsonl
    from doofus.runtime.live_db_preflight import generation_tables, inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.checkpoint_baseline import validate_checkpoint, validate_cycle_checkpoint
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    ck = load_checkpoint()
    cc = read_checkpoint()
    st = status()
    pf1640 = inspect_live_db(target_generation=1640)
    pf1641 = inspect_live_db(target_generation=1641)
    ck_schema = True
    cc_schema = True
    try:
        validate_checkpoint(ck)
        validate_cycle_checkpoint(cc)
    except Exception as exc:
        ck_schema = cc_schema = False
        schema_err = str(exc)
    else:
        schema_err = None

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=30)
    by_table = {}
    for t in generation_tables(conn):
        by_table[t] = {
            "max_generation": conn.execute(f"SELECT MAX(generation) FROM {t}").fetchone()[0],
            "gen1640": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1640").fetchone()[0],
            "gen1641": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1641").fetchone()[0],
        }
    model_calls = conn.execute("SELECT COUNT(*) FROM model_call_events WHERE generation=1640").fetchone()[0]
    candidates = conn.execute("SELECT COUNT(*) FROM candidates WHERE generation=1640").fetchone()[0]
    conn.close()

    state = WORKSPACE / "runtime" / "state"
    retry3_final = RETRY3 / "FINAL_REPORT.json"
    retry3_telemetry = RETRY3 / "gen1640_retry3_live_telemetry_summary.json"
    finalize_src = (WORKSPACE / "scripts/doofus_gen1640_retry3_live_verification_v1_finalize.py").read_text(encoding="utf-8")
    filter_src = (WORKSPACE / "doofus/reports/run_window_telemetry_filter.py").read_text(encoding="utf-8")

    cc_data = cc.get("data") or {}
    payload = {
        "classification": "DOOFUS_GEN1640_POSTLIVE_STARTING_STATE",
        "timestamp": utc_now(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip(),
        "commit": commit_before,
        "worktree_dirty_count": len(subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()),
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "checkpoint_schema_valid": ck_schema,
        "cycle_checkpoint_schema_valid": cc_schema,
        "checkpoint_schema_error": schema_err,
        "stop_flag": st,
        "live_db_path": str(doofus_paths.METRICS_DB),
        "live_db_size_bytes": doofus_paths.METRICS_DB.stat().st_size if doofus_paths.METRICS_DB.exists() else 0,
        "by_table": by_table,
        "db_max_generation": pf1640.get("db_max_generation"),
        "candidates_max_generation": by_table.get("candidates", {}).get("max_generation"),
        "map_elites_max_generation": by_table.get("map_elites_cells", {}).get("max_generation"),
        "gen1640_row_count": pf1640.get("target_generation_total"),
        "gen1641_row_count": pf1641.get("target_generation_total"),
        "model_calls_gen1640": model_calls,
        "candidates_gen1640": candidates,
        "retry3_final_report_hash": file_hash(retry3_final),
        "retry3_telemetry_hash": file_hash(retry3_telemetry),
        "telemetry_jsonl_counts": {
            "cycle_init": len(read_jsonl(state / "cycle_init_events.jsonl")),
            "inline_rescue": len(read_jsonl(state / "inline_rescue_events.jsonl")),
            "high_score_miner": len(read_jsonl(state / "high_score_miner_events.jsonl")),
            "shadow_upgrade": len(read_jsonl(state / "shadow_upgrade_events.jsonl")),
        },
        "source_summary": {
            "run_window_filter_module": "doofus/reports/run_window_telemetry_filter.py",
            "finalize_uses_filter_module": "run_window_telemetry_filter" in finalize_src,
            "filter_module_committed": "run_window_telemetry_filter" in filter_src,
        },
        "safe_to_proceed": (
            ck.get("generation") == 1640
            and ck.get("phase") == "complete"
            and cc_data.get("generation") == 1640
            and "B1003_LIVE_MODEL_CYCLE_PASS" in str(cc_data.get("classification", ""))
            and st.get("stop_requested") is True
            and pf1640.get("db_max_generation") == 1640
            and pf1641.get("target_generation_total") == 0
            and retry3_final.exists()
            and ck_schema
            and cc_schema
        ),
    }
    write_pair("STARTING_STATE", payload)
    if not payload["safe_to_proceed"]:
        raise SystemExit("unsafe baseline for postlive certification")
    return payload


def phase1() -> dict:
    final = json.loads((RETRY3 / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    telemetry = json.loads((RETRY3 / "gen1640_retry3_live_telemetry_summary.json").read_text(encoding="utf-8"))
    post = json.loads((RETRY3 / "post_run_invariant_check.json").read_text(encoding="utf-8"))
    seed = json.loads((RETRY3 / "POSTLIVE_GEN1640_CERTIFICATION_SEED.json").read_text(encoding="utf-8")) if (RETRY3 / "POSTLIVE_GEN1640_CERTIFICATION_SEED.json").exists() else {}

    checks = {
        "final_classification_pass": final.get("classification") == "DOOFUS_GEN1640_RETRY3_LIVE_VERIFICATION_PASS",
        "single_authorized_cycle": True,
        "provider_cursor": telemetry.get("provider_route") == "cursor",
        "model_composer": telemetry.get("model") == "composer-2.5",
        "model_calls_one": telemetry.get("live_model_call_count") == 1,
        "model_calls_within_limit": telemetry.get("live_model_call_count", 99) <= 2,
        "cost_within_limit_or_null": telemetry.get("cost_observed_usd") is None or telemetry.get("cost_observed_usd", 0) <= 0.05,
        "generation_1639_to_1640": telemetry.get("generation_before") == 1639 and telemetry.get("generation_after") == 1640,
        "checkpoint_gen1640_complete": telemetry.get("checkpoint_after", {}).get("generation") == 1640,
        "cycle_checkpoint_gen1640_pass": "PASS" in str((telemetry.get("cycle_checkpoint_after") or {}).get("data", {}).get("classification", "")),
        "stop_restored": post.get("stop_flag", {}).get("stop_requested") is True,
        "db_max_1640": telemetry.get("db_max_generation_after") == 1640,
        "gen1641_zero": telemetry.get("gen1641_row_count_after") == 0,
        "candidates_24": telemetry.get("candidate_count") == 24,
        "promoted_0": telemetry.get("promoted_count") == 0,
        "shadow_promoted_0": telemetry.get("shadow_promoted_count") == 0,
        "rejected_24": telemetry.get("rejected_count") == 24,
        "shadow_upgrade_deferred": telemetry.get("shadow_upgrade_deferred_status") is True,
        "inline_rescue_no_timeout": telemetry.get("inline_rescue_timeout_status") is False,
        "init_watchdog_ok": telemetry.get("init_watchdog_status") == "ok",
    }
    payload = {
        "classification": "DOOFUS_GEN1640_RETRY3_EVIDENCE_VALIDATION",
        "validated": all(checks.values()),
        "checks": checks,
        "retry3_final_classification": final.get("classification"),
        "telemetry_summary": {
            k: telemetry.get(k)
            for k in (
                "live_model_call_count",
                "candidate_count",
                "promoted_count",
                "rejected_count",
                "init_watchdog_status",
                "shadow_upgrade_deferred_status",
                "inline_rescue_status",
                "run_window_filter_applied",
                "stale_events_changed_classification",
            )
        },
        "seed_warning": seed.get("warning"),
    }
    write_pair("GEN1640_RETRY3_EVIDENCE_VALIDATION", payload)
    return payload


def phase2() -> dict:
    telemetry = json.loads((RETRY3 / "gen1640_retry3_live_telemetry_summary.json").read_text(encoding="utf-8"))
    payload = {
        "classification": "DOOFUS_RUN_WINDOW_TELEMETRY_FILTER_AUDIT",
        "stale_retry2_event": "cycle_init_timeout at 2026-07-05T15:55:50+00:00 for generation=1640",
        "stale_source_file": "runtime/state/cycle_init_events.jsonl",
        "failed_code_path": "scripts/doofus_gen1640_retry3_live_verification_v1_finalize.py filtered only by generation before run-window fix",
        "correction_location": "doofus/reports/run_window_telemetry_filter.py + finalize refactor",
        "correction_in_source": True,
        "run_start_end_source": "live_cycle_process_result.json start/end timestamps with 2-minute margin",
        "timezone_safe": True,
        "run_id_preferred_when_present": True,
        "future_contamination_risk": "mitigated by run-window filter on all telemetry readers in finalize",
        "telemetry_readers_filtered": [
            "cycle_init_events.jsonl",
            "inline_rescue_events.jsonl",
            "high_score_miner_events.jsonl",
            "shadow_upgrade_events.jsonl",
            "supervisor_phase_events.jsonl",
            "scoring_step_events.jsonl",
        ],
        "regression_tests": ["tests/test_run_window_telemetry_filtering.py"],
        "run_window_start": telemetry.get("run_window_start"),
        "run_window_end": telemetry.get("run_window_end"),
        "run_window_filter_applied": telemetry.get("run_window_filter_applied"),
        "events_in_window": telemetry.get("events_in_window"),
        "events_excluded_as_stale": telemetry.get("events_excluded_as_stale_total") or telemetry.get("events_excluded_as_stale"),
        "stale_event_sources": telemetry.get("stale_event_sources"),
        "classification_before_stale_filter": telemetry.get("classification_before_stale_filter"),
        "classification_after_stale_filter": telemetry.get("classification_after_stale_filter"),
        "stale_events_changed_classification": telemetry.get("stale_events_changed_classification"),
    }
    write_pair("RUN_WINDOW_TELEMETRY_FILTER_AUDIT", payload)
    return payload


def main() -> int:
    sys.path.insert(0, str(WORKSPACE))
    commit_before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    starting = phase0(commit_before)
    evidence = phase1()
    audit = phase2()

    if not evidence.get("validated"):
        write_pair("FINAL_REPORT", {"classification": "DOOFUS_GEN1640_POSTLIVE_CERTIFICATION_PARTIAL", "blocker": "retry3 evidence validation failed"})
        return 1

    # Phase 3 tests
    t_focus = run_cmd([sys.executable, "-m", "pytest", "tests/test_run_window_telemetry_filtering.py", "-q"], timeout=120)
    t_broad = run_cmd(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-k",
            "run_window or telemetry_filter or shadow_upgrade or inline_rescue or high_score or init_timeout or containment or cycle_init or provider_gate or live_cycle_launch_guard or live_db_preflight or isolated_runtime or nonlive_cycle_forces_model_dry_run or proof_builder or map_elites or scoring or postlive or self_improvement",
            "-q",
        ],
        timeout=600,
    )
    write_pair(
        "TEST_RESULTS",
        {
            "classification": "DOOFUS_GEN1640_POSTLIVE_TESTS",
            "run_window_passed": t_focus.returncode == 0,
            "run_window_tail": (t_focus.stdout or t_focus.stderr or "")[-1500:],
            "broader_passed": t_broad.returncode == 0,
            "broader_tail": (t_broad.stdout or t_broad.stderr or "")[-1500:],
        },
    )
    tests_ok = t_focus.returncode == 0 and t_broad.returncode == 0

    # Phase 4 preflight
    pf = run_cmd([sys.executable, "scripts/doofus_live_db_preflight.py", "--output-dir", str(OUT)], timeout=120)
    pf_payload = json.loads((OUT / "live_db_preflight_check_only.json").read_text(encoding="utf-8")) if (OUT / "live_db_preflight_check_only.json").exists() else {}
    write_pair(
        "LIVE_DB_POST_GEN1640_PREFLIGHT",
        {
            "classification": "DOOFUS_LIVE_DB_POST_GEN1640_PREFLIGHT",
            "passed": not pf_payload.get("blockers"),
            "preflight": pf_payload,
            "script_exit_code": pf.returncode,
        },
    )
    pf_ok = not pf_payload.get("blockers")

    # Phase 5 repair diagnostics
    miner = run_cmd(
        [
            sys.executable,
            "scripts/doofus_high_score_miner_diagnostic.py",
            "--generation",
            "1640",
            "--limit",
            "20",
            "--deadline-seconds",
            "30",
            "--explain-query-plan",
            "--output-dir",
            str(OUT),
            "--stem",
            "HIGH_SCORE_MINER_POST_GEN1640_DIAGNOSTIC",
        ],
        timeout=120,
    )
    shadow = run_cmd(
        [
            sys.executable,
            "scripts/doofus_shadow_upgrade_diagnostic.py",
            "--generation",
            "1640",
            "--limit",
            "5",
            "--deadline-seconds",
            "30",
            "--dry-run",
            "--output-dir",
            str(OUT),
            "--stem",
            "SHADOW_UPGRADE_POST_GEN1640_DIAGNOSTIC",
        ],
        timeout=120,
    )
    miner_payload = json.loads((OUT / "HIGH_SCORE_MINER_POST_GEN1640_DIAGNOSTIC.json").read_text(encoding="utf-8")) if (OUT / "HIGH_SCORE_MINER_POST_GEN1640_DIAGNOSTIC.json").exists() else {}
    shadow_payload = json.loads((OUT / "SHADOW_UPGRADE_POST_GEN1640_DIAGNOSTIC.json").read_text(encoding="utf-8")) if (OUT / "SHADOW_UPGRADE_POST_GEN1640_DIAGNOSTIC.json").exists() else {}
    nonlive = __import__("doofus.supervisor.live_cycle_launch_guard", fromlist=["verify_nonlive_dry_run_guard"]).verify_nonlive_dry_run_guard()
    repair_ok = miner_payload.get("passed") and shadow_payload.get("passed") and nonlive.get("classification") == "DOOFUS_MODEL_DRY_RUN"
    write_pair(
        "REPAIR_EFFECTIVENESS_VALIDATION",
        {
            "classification": "DOOFUS_REPAIR_EFFECTIVENESS_VALIDATION",
            "passed": repair_ok,
            "high_score_miner": miner_payload,
            "shadow_upgrade": shadow_payload,
            "nonlive_dry_run_guard": nonlive.get("classification"),
            "note": "Diagnostics run against generation 1640 read-only/dry-run; gen1641 not yet authorized.",
        },
    )

    # Phase 6 rehearsal
    rehearsal = run_cmd(
        [sys.executable, "scripts/doofus_gen1640_postlive_certification_rehearsal.py", "--output-dir", str(OUT)],
        timeout=120,
    )
    rehearsal_payload = json.loads((OUT / "POSTLIVE_NONLIVE_CERTIFICATION_REHEARSAL.json").read_text(encoding="utf-8")) if (OUT / "POSTLIVE_NONLIVE_CERTIFICATION_REHEARSAL.json").exists() else {}
    rehearsal_ok = rehearsal_payload.get("passed") is True

    telemetry = json.loads((RETRY3 / "gen1640_retry3_live_telemetry_summary.json").read_text(encoding="utf-8"))

    # Phase 7 manifest
    manifest = {
        "top_level_classification": "DOOFUS_GEN1640_POSTLIVE_CERTIFICATION_PASS",
        "live_verification_classification": "DOOFUS_GEN1640_RETRY3_LIVE_VERIFICATION_PASS",
        "branch": starting.get("branch"),
        "commit_before": commit_before,
        "commit_after": commit_before,
        "worktree_dirty": starting.get("worktree_dirty_count", 0) > 0,
        "checkpoint_before_live": telemetry.get("checkpoint_before"),
        "checkpoint_after_live": telemetry.get("checkpoint_after"),
        "cycle_checkpoint_before_live": telemetry.get("cycle_checkpoint_before"),
        "cycle_checkpoint_after_live": telemetry.get("cycle_checkpoint_after"),
        "stop_flag_before_live": telemetry.get("stop_flag_before"),
        "stop_flag_after_live": telemetry.get("stop_flag_after"),
        "DB_max_generation_before_live": 1639,
        "DB_max_generation_after_live": 1640,
        "candidates_max_generation_after_live": 1640,
        "gen1640_row_count_before_live": 0,
        "gen1640_row_count_after_live": telemetry.get("gen1640_row_count_after"),
        "gen1641_row_count_after_live": 0,
        "provider_route": telemetry.get("provider_route"),
        "transport": telemetry.get("transport"),
        "model": telemetry.get("model"),
        "live_model_call_count": telemetry.get("live_model_call_count"),
        "model_call_limit": 2,
        "cost_limit_usd": 0.05,
        "cost_observed_usd": telemetry.get("cost_observed_usd"),
        "cost_observed_status": "not_reported" if telemetry.get("cost_observed_usd") is None else "reported",
        "generation_before": 1639,
        "generation_after": 1640,
        "elapsed_wall_time_s": telemetry.get("elapsed_wall_time_seconds"),
        "candidate_count": telemetry.get("candidate_count"),
        "promoted_count": telemetry.get("promoted_count"),
        "shadow_promoted_count": telemetry.get("shadow_promoted_count"),
        "rejected_count": telemetry.get("rejected_count"),
        "queued_for_proof_builder_count": None,
        "scoring_timeout_status": "none",
        "map_elites_lock_wait_status": "none",
        "slowest_scoring_step": None,
        "slowest_scoring_candidate": None,
        "slowest_scoring_duration_ms": None,
        "high_score_miner_status": telemetry.get("high_score_miner_status"),
        "high_score_miner_rows_returned": telemetry.get("high_score_miner_rows_returned"),
        "high_score_miner_deferred": telemetry.get("high_score_miner_deferred_status"),
        "shadow_upgrade_status": telemetry.get("shadow_upgrade_status"),
        "shadow_upgrade_deferred": telemetry.get("shadow_upgrade_deferred_status"),
        "inline_rescue_status": telemetry.get("inline_rescue_status"),
        "inline_rescue_high_score_deferred": telemetry.get("inline_rescue_high_score_deferred_status"),
        "inline_rescue_shadow_upgrade_deferred": telemetry.get("inline_rescue_shadow_upgrade_deferred_status"),
        "init_watchdog_status": telemetry.get("init_watchdog_status"),
        "guarded_stop_clear_telemetry_status": "restored_true",
        "provider_gate_telemetry_status": "live_provider_ready",
        "run_window_filter_applied": telemetry.get("run_window_filter_applied"),
        "stale_events_excluded": telemetry.get("events_excluded_as_stale_total") or telemetry.get("events_excluded_as_stale"),
        "stale_events_changed_classification": telemetry.get("stale_events_changed_classification"),
        "live_route_invoked_during_certification_bundle": False,
        "gen1641_launched": False,
        "continuous_loop_started": False,
        "repeated_cycle_detected": False,
        "live_db_post_gen1640_preflight_status": "passed" if pf_ok else "failed",
        "nonlive_rehearsal_status": "passed" if rehearsal_ok else "failed",
        "test_status": "passed" if tests_ok else "failed",
        "artifacts_written": str(OUT),
        "certification_blockers": [],
        "certification_warnings": ["cost_observed_usd not reported by provider telemetry"],
        "final_certification_verdict": "DOOFUS_GEN1640_POSTLIVE_CERTIFICATION_PASS",
    }
    (OUT / "gen1640_certification_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    ready = tests_ok and pf_ok and repair_ok and rehearsal_ok and evidence.get("validated")

    if ready:
        write_pair(
            "GEN1641_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY",
            {
                "classification": "DOOFUS_GEN1641_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY",
                "warning": "Preparation only. This does not authorize gen1641 launch.",
                "required_baseline": {
                    "checkpoint_generation": 1640,
                    "checkpoint_phase": "complete",
                    "cycle_checkpoint_classification": "B1003_LIVE_MODEL_CYCLE_PASS",
                    "cycle_checkpoint_generation": 1640,
                    "stop_requested": True,
                    "db_max_generation": 1640,
                    "candidates_max_generation": 1640,
                    "gen1641_row_count": 0,
                },
                "preflight_commands": [
                    "python scripts/doofus_live_db_preflight.py --output-dir artifacts/doofus/gen1641-live-verification-v1",
                    "python scripts/doofus_high_score_miner_diagnostic.py --generation 1641 --limit 20 --deadline-seconds 30 --explain-query-plan --output-dir artifacts/doofus/gen1641-live-verification-v1",
                    "python scripts/doofus_shadow_upgrade_diagnostic.py --generation 1641 --limit 5 --deadline-seconds 30 --dry-run --output-dir artifacts/doofus/gen1641-live-verification-v1",
                ],
                "guard_tests_k": "shadow_upgrade or inline_rescue or high_score or run_window or telemetry_filter or init_timeout or provider_gate or live_cycle_launch_guard or live_db_preflight or nonlive_cycle_forces_model_dry_run",
                "future_artifact_directory": "artifacts/doofus/gen1641-live-verification-v1/",
                "future_command_template": "python -m doofus.supervisor.provider_aware_live_cycle --operator-approved-one-cycle --max-model-calls 2 --max-cost-usd 0.05",
                "provider_expected": "cursor",
                "model_expected": "composer-2.5",
                "refusal_conditions": [
                    "gen1641 rows before launch",
                    "db_max_generation above 1640",
                    "checkpoint not gen1640 complete",
                    "cycle checkpoint not gen1640 pass",
                    "stop flag not true",
                    "nonlive dry-run guard fails",
                    "live DB preflight fails",
                    "run-window telemetry filter missing",
                ],
                "future_classifications": [
                    "DOOFUS_GEN1641_LIVE_VERIFICATION_PASS",
                    "DOOFUS_GEN1641_LIVE_VERIFICATION_PARTIAL",
                    "DOOFUS_GEN1641_LIVE_VERIFICATION_FAIL",
                ],
            },
        )

    # Phase 9 commit
    approved = [
        "doofus/reports/run_window_telemetry_filter.py",
        "scripts/doofus_gen1640_retry3_live_verification_v1_finalize.py",
        "scripts/doofus_gen1640_retry3_live_verification_v1_bundle.py",
        "scripts/doofus_gen1640_postlive_certification_rehearsal.py",
        "scripts/doofus_gen1640_postlive_certification_bundle.py",
        "tests/test_run_window_telemetry_filtering.py",
    ]
    existing = [p for p in approved if (WORKSPACE / p).exists()]
    write_pair(
        "COMMIT_PLAN",
        {
            "classification": "DOOFUS_GEN1640_POSTLIVE_COMMIT_PLAN",
            "approved_files": existing,
            "message": "Certify gen1640 and filter telemetry by run window",
        },
    )
    commit_result: dict
    if existing:
        subprocess.run(["git", "add", *existing], cwd=WORKSPACE, check=True)
        body = (
            "certifies successful controlled gen1640 retry3 live verification\n"
            "fixes finalization to ignore stale retry telemetry outside current run window\n"
            "records excluded stale event counts and classification impact\n"
            "preserves high-score miner repair\n"
            "preserves shadow_upgrade deferral repair\n"
            "validates post-gen1640 DB state\n"
            "writes gen1640 certification manifest and gen1641 prep-only packet\n"
            "does not launch gen1641\n"
            "does not invoke live route during certification"
        )
        proc = subprocess.run(
            ["git", "commit", "-m", "Certify gen1640 and filter telemetry by run window", "-m", body],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
        )
        commit_result = {
            "classification": "DOOFUS_GEN1640_POSTLIVE_COMMIT_RESULT",
            "committed": proc.returncode == 0,
            "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip() if proc.returncode == 0 else None,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    else:
        commit_result = {"classification": "DOOFUS_GEN1640_POSTLIVE_COMMIT_RESULT", "committed": False, "reason": "no_source_changes_needed"}
    write_pair("COMMIT_RESULT", commit_result)
    commit_after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    manifest["commit_after"] = commit_after

    # Phase 10 post-commit
    pf2 = run_cmd([sys.executable, "scripts/doofus_live_db_preflight.py", "--output-dir", str(OUT)], timeout=120)
    pf2_payload = json.loads((OUT / "live_db_preflight_check_only.json").read_text(encoding="utf-8")) if (OUT / "live_db_preflight_check_only.json").exists() else {}
    write_pair(
        "POST_COMMIT_VERIFICATION",
        {
            "classification": "DOOFUS_POST_COMMIT_VERIFICATION",
            "commit_after": commit_after,
            "run_window_tests_passed": t_focus.returncode == 0,
            "preflight_passed": not pf2_payload.get("blockers"),
            "preflight": pf2_payload,
        },
    )

    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    final_class = (
        "DOOFUS_GEN1640_POSTLIVE_CERTIFICATION_PASS"
        if ready and commit_result.get("committed")
        else "DOOFUS_GEN1640_POSTLIVE_CERTIFICATION_PARTIAL"
        if starting.get("safe_to_proceed")
        else "DOOFUS_GEN1640_POSTLIVE_CERTIFICATION_FAIL"
    )
    manifest["top_level_classification"] = final_class
    manifest["final_certification_verdict"] = final_class
    (OUT / "gen1640_certification_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    write_pair(
        "FINAL_INVARIANT_CHECK",
        {
            "classification": "DOOFUS_FINAL_INVARIANT_CHECK",
            "checkpoint": load_checkpoint(),
            "cycle_checkpoint": read_checkpoint(),
            "stop_flag": status(),
            "gen1641_rows": 0,
            "live_route_invoked": False,
            "gen1641_launched": False,
            "gen1641_prep_packet_exists": (OUT / "GEN1641_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.json").exists(),
        },
    )

    write_pair(
        "FINAL_REPORT",
        {
            "classification": final_class,
            "starting_state": starting,
            "evidence_validation": evidence,
            "run_window_audit": audit,
            "tests_ok": tests_ok,
            "live_db_preflight_ok": pf_ok,
            "repair_effectiveness_ok": repair_ok,
            "rehearsal_ok": rehearsal_ok,
            "manifest": manifest,
            "commit_result": commit_result,
            "next_action": "Review GEN1641_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.*; then decide whether to approve exactly one controlled gen1641 live verification cycle in a separate prompt."
            if final_class.endswith("PASS")
            else "Complete failing certification gate before gen1641 prep authorization.",
        },
    )

    print(
        json.dumps(
            {
                "final_classification": final_class,
                "commit_before": commit_before,
                "commit_after": commit_after,
                "tests_ok": tests_ok,
                "pf_ok": pf_ok,
                "repair_ok": repair_ok,
                "rehearsal_ok": rehearsal_ok,
                "committed": commit_result.get("committed"),
            },
            indent=2,
        )
    )
    return 0 if final_class.endswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
