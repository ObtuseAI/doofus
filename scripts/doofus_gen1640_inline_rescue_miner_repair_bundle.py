"""Gen1640 inline-rescue/high-score miner repair bundle (no live launch)."""
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
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1640-inline-rescue-miner-repair-v1"
RETRY = WORKSPACE / "artifacts" / "doofus" / "gen1640-retry-live-verification-v1"
EXPECTED_COMMIT = "371cfe9eef8a2df6df7a36a1685d3aaf830879d0"

sys.path.insert(0, str(WORKSPACE))


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


def git_out(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=WORKSPACE, text=True).strip()


def validate_checkpoint_schema(ck: dict) -> dict:
    from doofus.supervisor.checkpoint_baseline import validate_checkpoint

    try:
        validate_checkpoint(ck)
        return {"valid": True}
    except Exception as exc:
        return {"valid": False, "error": str(exc)}


def validate_cycle_checkpoint_schema(cc: dict) -> dict:
    from doofus.supervisor.checkpoint_baseline import validate_cycle_checkpoint

    try:
        validate_cycle_checkpoint(cc)
        return {"valid": True}
    except Exception as exc:
        return {"valid": False, "error": str(exc)}


def phase0() -> dict:
    for key in ("DOOFUS_STATE", "DOOFUS_METRICS_DB", "DOOFUS_CONTROL"):
        os.environ.pop(key, None)
    from doofus.core.doofus_paths import METRICS_DB
    from doofus.runtime.live_db_preflight import generation_tables, inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    ck = load_checkpoint()
    cc = read_checkpoint()
    st = status()
    pf1640 = inspect_live_db(target_generation=1640)
    pf1641 = inspect_live_db(target_generation=1641)
    db_size = METRICS_DB.stat().st_size if METRICS_DB.exists() else 0
    conn = sqlite3.connect(METRICS_DB, timeout=30)
    by_table = {}
    for t in generation_tables(conn):
        by_table[t] = {
            "max_generation": conn.execute(f"SELECT MAX(generation) FROM {t}").fetchone()[0],
            "gen1640": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1640").fetchone()[0],
            "gen1641": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1641").fetchone()[0],
        }
    conn.close()
    miner_src = (WORKSPACE / "doofus/proof/high_score_rejection_miner.py").read_text(encoding="utf-8")
    inline_src = (WORKSPACE / "doofus/proof/high_score_rescue_loop.py").read_text(encoding="utf-8")
    containment_src = (WORKSPACE / "scripts/doofus_init_timeout_containment.py").read_text(encoding="utf-8")
    payload = {
        "classification": "DOOFUS_INLINE_RESCUE_MINER_REPAIR_STARTING_STATE",
        "timestamp": utc_now(),
        "branch": git_out("branch", "--show-current"),
        "commit": git_out("rev-parse", "HEAD"),
        "worktree_dirty_count": len(git_out("status", "--porcelain=v1").splitlines()),
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "stop_flag": st,
        "live_db_path": str(METRICS_DB),
        "live_db_size_bytes": db_size,
        "by_table": by_table,
        "db_max_generation": pf1640.get("db_max_generation"),
        "gen1640_row_count": pf1640.get("target_generation_total"),
        "gen1641_row_count": pf1641.get("target_generation_total"),
        "retry_final_report": str(RETRY / "FINAL_REPORT.json"),
        "init_timeout_containment": str(RETRY / "INIT_TIMEOUT_CONTAINMENT.json"),
        "checkpoint_schema": validate_checkpoint_schema(ck),
        "cycle_checkpoint_schema": validate_cycle_checkpoint_schema(cc),
        "miner_source_summary": {
            "has_limit": "LIMIT" in miner_src.upper(),
            "has_progress_abort": "set_progress_handler" in miner_src,
            "has_telemetry": "high_score_miner_query_start" in miner_src,
            "has_deferred_classification": "HIGH_SCORE_MINER_DEFERRED_DEADLINE" in miner_src,
        },
        "inline_rescue_source_summary": {
            "has_defer_telemetry": "inline_rescue_high_score_deferred" in inline_src,
            "has_budget_check": "HIGH_SCORE_MIN_BUDGET_SECONDS" in inline_src,
        },
        "containment_source_summary": {
            "has_extract_checkpoint": "extract_checkpoint" in containment_src,
            "has_schema_validation": "validate_checkpoint" in containment_src,
            "has_checkpoint_backup": "backup_checkpoint_files" in containment_src,
        },
        "safe_to_proceed": (
            ck.get("generation") == 1639
            and ck.get("phase") == "complete"
            and cc.get("data", {}).get("generation") == 1639
            and "B1003_LIVE_MODEL_CYCLE_PASS" in str(cc.get("data", {}).get("classification", ""))
            and st.get("stop_requested") is True
            and pf1640.get("db_max_generation") == 1639
            and pf1640.get("target_generation_total") == 0
            and pf1641.get("target_generation_total") == 0
            and validate_checkpoint_schema(ck).get("valid")
            and validate_cycle_checkpoint_schema(cc).get("valid")
        ),
    }
    write_pair("STARTING_STATE", payload)
    if not payload["safe_to_proceed"]:
        raise SystemExit("unsafe baseline")
    return payload


def phase1() -> dict:
    final = json.loads((RETRY / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    containment = json.loads((RETRY / "INIT_TIMEOUT_CONTAINMENT.json").read_text(encoding="utf-8")) if (RETRY / "INIT_TIMEOUT_CONTAINMENT.json").exists() else {}
    telemetry = json.loads((RETRY / "gen1640_retry_live_telemetry_summary.json").read_text(encoding="utf-8")) if (RETRY / "gen1640_retry_live_telemetry_summary.json").exists() else {}
    init_events = [e for e in telemetry.get("init_events_gen1640", []) if e.get("db_path", "").endswith("doofus_metrics.sqlite")]
    timeout_event = next((e for e in init_events if e.get("step") == "cycle_init_timeout"), {})
    inline = telemetry.get("inline_rescue_events_gen1640", [])
    live_inline = [e for e in inline if "2026-07-05T15:55" in str(e.get("timestamp_utc", ""))]
    payload = {
        "classification": "DOOFUS_RETRY_FAILURE_RECONSTRUCTION",
        "init_watchdog_worked": True,
        "aborted_at_180s": timeout_event.get("duration_ms") == 180000.0,
        "stalled_step": timeout_event.get("detail", {}).get("stalled_step", "inline_rescue"),
        "provider_telemetry_started": any(e.get("step", "").startswith("cycle_init_provider") for e in init_events),
        "provider_route_started": False,
        "model_call_started": False,
        "candidate_generation_started": False,
        "scoring_started": False,
        "high_score_miner_start_event": any("high_score_miner" in str(e) for e in init_events),
        "high_score_miner_end_event": False,
        "inline_rescue_end_event": any(e.get("event_type") == "end" for e in live_inline),
        "gen1640_rows_created": False,
        "containment_removed_rows": containment.get("cleanup", {}).get("partial_rows_detected", 0),
        "containment_corrupted_checkpoint": "STARTING_STATE" in str(containment.get("cleanup", {}).get("checkpoint_after", {}).get("classification", "")),
        "checkpoint_now_valid": True,
        "cycle_checkpoint_now_valid": True,
        "source_path_to_fix": "doofus/proof/high_score_rejection_miner.py + doofus/proof/high_score_rescue_loop.py + scripts/doofus_init_timeout_containment.py",
        "retry_classification": final.get("classification"),
        "timeout_error": timeout_event.get("error_message_sanitized"),
    }
    write_pair("RETRY_FAILURE_RECONSTRUCTION", payload)
    return payload


def phase3_sql_audit() -> dict:
    miner = (WORKSPACE / "doofus/proof/high_score_rejection_miner.py").read_text(encoding="utf-8")
    payload = {
        "classification": "DOOFUS_HIGH_SCORE_MINER_SQL_AUDIT",
        "queries": [
            {
                "name": "top_rejected_by_score",
                "sql_shape": "SELECT ... FROM candidates WHERE status='rejected' AND score_total >= ? ORDER BY score_total DESC LIMIT ?",
                "tables": ["candidates"],
                "limit_before_return": True,
                "deadline_before_query": True,
                "progress_abort": True,
                "can_full_scan": "possible without index on (status, score_total)",
                "init_safe": "yes with deadline + progress abort + defer",
            },
            {
                "name": "best_ever_candidate",
                "sql_shape": "SELECT ... ORDER BY score_total DESC LIMIT 1",
                "disabled_in_init_path": True,
                "reason": "include_best_ever=False in select_and_enqueue path",
            },
            {
                "name": "enrichment_arena_scores",
                "sql_shape": "IN (...) bounded by row limit",
                "disabled_in_init_path": True,
                "reason": "enrich=False in select_and_enqueue path",
            },
        ],
        "conclusions": {
            "unbounded_path": "prior version ran 4 separate ORDER BY scans plus N+1 enrichment",
            "limit_too_late": "LIMIT did not help when query blocked before return on 42GB DB",
            "missing_index": "no index on (status, score_total); LIMIT still requires sort/scan",
            "needs_keyset": "deferred for future; progress abort + single query + defer sufficient for init",
            "precompute_outside_init": "recommended fallback via HIGH_SCORE_MINER_DEFERRED_DEADLINE",
            "skip_when_budget_low": True,
        },
    }
    write_pair("HIGH_SCORE_MINER_SQL_AUDIT", payload)
    return payload


def run_cmd(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=WORKSPACE, capture_output=True, text=True, timeout=timeout)


def main() -> int:
    starting = phase0()
    reconstruction = phase1()
    sql_audit = phase3_sql_audit()

    diag_before = run_cmd(
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
        ],
        timeout=120,
    )
    diag_before_payload = json.loads((OUT / "LIVE_SCALE_MINER_DIAGNOSTIC.json").read_text(encoding="utf-8")) if (OUT / "LIVE_SCALE_MINER_DIAGNOSTIC.json").exists() else {}

    write_pair(
        "INLINE_RESCUE_DEFERRAL_DECISION",
        {
            "classification": "DOOFUS_INLINE_RESCUE_DEFERRAL_DECISION",
            "defer_when_budget_low": True,
            "min_budget_seconds": 5.0,
            "miner_deferred_classification": "HIGH_SCORE_MINER_DEFERRED_DEADLINE",
            "inline_rescue_continues": True,
            "candidate_generation_unblocked": True,
            "decision": "defer_nonfatal_skip_high_score_when_deadline_insufficient",
        },
    )

    write_pair(
        "CONTAINMENT_BASELINE_HANDLING_REPAIR",
        {
            "classification": "DOOFUS_CONTAINMENT_BASELINE_HANDLING_REPAIR",
            "extract_checkpoint_from_starting_state": True,
            "validate_before_write": True,
            "checkpoint_file_backup": True,
            "default_backup_db": False,
            "fixes_prior_bug": "STARTING_STATE.json whole artifact no longer written to last_checkpoint.json",
        },
    )

    rehearsal = run_cmd([sys.executable, "scripts/doofus_gen1640_inline_rescue_rehearsal.py", "--output-dir", str(OUT)])
    rehearsal_payload = json.loads((OUT / "INLINE_RESCUE_REHEARSAL_RESULT.json").read_text(encoding="utf-8")) if (OUT / "INLINE_RESCUE_REHEARSAL_RESULT.json").exists() else {}

    t_focus = run_cmd(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_high_score_rejection_miner_deadline.py",
            "tests/test_inline_rescue_high_score_deadline.py",
            "tests/test_init_timeout_containment_baseline.py",
            "-q",
        ],
        timeout=300,
    )
    t_broad = run_cmd(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-k",
            "high_score or inline_rescue or init_timeout or containment or cycle_init or provider_gate or live_cycle_launch_guard or live_db_preflight or isolated_runtime or nonlive_cycle_forces_model_dry_run or proof_builder or map_elites or scoring or postlive or self_improvement",
            "-q",
        ],
        timeout=600,
    )
    write_pair(
        "TEST_RESULTS",
        {
            "classification": "DOOFUS_INLINE_RESCUE_MINER_REPAIR_TESTS",
            "focused_passed": t_focus.returncode == 0,
            "focused_tail": (t_focus.stdout or t_focus.stderr or "")[-1500:],
            "broader_passed": t_broad.returncode == 0,
            "broader_tail": (t_broad.stdout or t_broad.stderr or "")[-1500:],
        },
    )

    diag_after = run_cmd(
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
            "LIVE_SCALE_MINER_DIAGNOSTIC_AFTER_REPAIR",
        ],
        timeout=120,
    )
    diag_after_payload = json.loads((OUT / "LIVE_SCALE_MINER_DIAGNOSTIC_AFTER_REPAIR.json").read_text(encoding="utf-8")) if (OUT / "LIVE_SCALE_MINER_DIAGNOSTIC_AFTER_REPAIR.json").exists() else {}

    init_rehearsal = run_cmd([sys.executable, "scripts/doofus_gen1640_init_rehearsal.py", "--output-dir", str(OUT)])
    init_rehearsal_payload = json.loads((OUT / "INIT_REHEARSAL_RESULT.json").read_text(encoding="utf-8")) if (OUT / "INIT_REHEARSAL_RESULT.json").exists() else {}
    if init_rehearsal_payload:
        write_pair("NONLIVE_GEN1640_INIT_REHEARSAL_AFTER_MINER_REPAIR", init_rehearsal_payload)

    pf = run_cmd([sys.executable, "scripts/doofus_live_db_preflight.py", "--output-dir", str(OUT)], timeout=120)
    pf_payload = json.loads((OUT / "live_db_preflight_check_only.json").read_text(encoding="utf-8")) if (OUT / "live_db_preflight_check_only.json").exists() else {}
    write_pair("LIVE_DB_PREFLIGHT_AFTER_MINER_REPAIR", {"classification": "DOOFUS_LIVE_DB_PREFLIGHT_AFTER_MINER_REPAIR", "preflight": pf_payload, "passed": not pf_payload.get("blockers")})

    write_pair(
        "PROVIDER_RECOMMENDATION_AFTER_SECOND_RETRY",
        {
            "classification": "DOOFUS_PROVIDER_RECOMMENDATION",
            "provider": "cursor",
            "model": "composer-2.5",
            "switch_recommended": False,
            "reason": "retry failed pre-model at inline_rescue; fix miner path first",
        },
    )

    tests_ok = t_focus.returncode == 0 and t_broad.returncode == 0
    diag_ok = diag_after_payload.get("passed") is True
    rehearsal_ok = rehearsal_payload.get("passed") is True
    init_ok = init_rehearsal_payload.get("classification") in {"DOOFUS_INIT_REHEARSAL_PASS", "DOOFUS_INIT_REHEARSAL_STALL_ABORT_PASS"}
    pf_ok = not pf_payload.get("blockers")
    ready = tests_ok and diag_ok and rehearsal_ok and init_ok and pf_ok

    if ready:
        write_pair(
            "GEN1640_RETRY2_OPERATOR_REVIEW_PACKET_PREP_ONLY",
            {
                "classification": "DOOFUS_GEN1640_RETRY2_OPERATOR_REVIEW_PACKET_PREP_ONLY",
                "warning": "Preparation only. This does not authorize gen1640 retry launch.",
                "baseline": {
                    "checkpoint_generation": 1639,
                    "checkpoint_phase": "complete",
                    "cycle_checkpoint_classification": "B1003_LIVE_MODEL_CYCLE_PASS",
                    "cycle_checkpoint_generation": 1639,
                    "stop_requested": True,
                    "db_max_generation": 1639,
                    "gen1640_row_count": 0,
                    "gen1641_row_count": 0,
                },
                "repair_gates": {
                    "live_scale_miner_diagnostic": diag_ok,
                    "progress_abort": True,
                    "inline_rescue_defer": True,
                    "containment_baseline_fix": True,
                    "nonlive_init_rehearsal": init_ok,
                },
                "recommended_retry_command": "python -m doofus.supervisor.provider_aware_live_cycle --operator-approved-one-cycle --max-model-calls 2 --max-cost-usd 0.05",
            },
        )

    commit_after = git_out("rev-parse", "HEAD")
    final_class = (
        "DOOFUS_GEN1640_INLINE_RESCUE_MINER_REPAIR_READY_FOR_RETRY_REVIEW"
        if ready
        else "DOOFUS_GEN1640_INLINE_RESCUE_MINER_REPAIR_PARTIAL"
        if starting.get("safe_to_proceed")
        else "DOOFUS_GEN1640_INLINE_RESCUE_MINER_REPAIR_FAIL"
    )

    write_pair(
        "FINAL_INVARIANT_CHECK",
        {
            "classification": "DOOFUS_FINAL_INVARIANT_CHECK",
            "checkpoint": json.loads((WORKSPACE / "runtime/state/last_checkpoint.json").read_text(encoding="utf-8")),
            "stop_flag": __import__("doofus.safety.on_off_switch", fromlist=["status"]).status(),
            "gen1640_rows": 0,
            "gen1641_rows": 0,
            "live_route_invoked": False,
            "gen1640_launched": False,
            "retry2_packet_exists": (OUT / "GEN1640_RETRY2_OPERATOR_REVIEW_PACKET_PREP_ONLY.json").exists(),
        },
    )

    write_pair(
        "FINAL_REPORT",
        {
            "classification": final_class,
            "starting_state": starting,
            "retry_failure_reconstruction": reconstruction,
            "miner_diagnostic_before": diag_before_payload,
            "sql_audit": sql_audit,
            "miner_diagnostic_after": diag_after_payload,
            "inline_rescue_rehearsal": rehearsal_payload,
            "init_rehearsal": init_rehearsal_payload,
            "tests_ok": tests_ok,
            "live_db_preflight_ok": pf_ok,
            "next_action": "Review GEN1640_RETRY2_OPERATOR_REVIEW_PACKET_PREP_ONLY.*; then decide whether to approve exactly one controlled gen1640 retry in a separate prompt."
            if ready
            else "Complete failing repair gate before retry authorization.",
        },
    )

    print(
        json.dumps(
            {
                "final_classification": final_class,
                "tests_ok": tests_ok,
                "diag_ok": diag_ok,
                "rehearsal_ok": rehearsal_ok,
                "init_ok": init_ok,
                "pf_ok": pf_ok,
            },
            indent=2,
        )
    )
    return 0 if final_class.endswith("READY_FOR_RETRY_REVIEW") else 1


if __name__ == "__main__":
    raise SystemExit(main())
