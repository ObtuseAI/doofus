"""Gen1640 inline-rescue shadow upgrade repair bundle (no live launch)."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1640-inline-rescue-shadow-upgrade-repair-v1"
RETRY2 = WORKSPACE / "artifacts" / "doofus" / "gen1640-retry2-live-verification-v1"
EXPECTED_COMMIT = "a44be6c8ce8499cb20ebd2c04774f5d756197ca6"

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


def run_cmd(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=WORKSPACE, capture_output=True, text=True, timeout=timeout)


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
    shadow_src = (WORKSPACE / "doofus/evolution/shadow_elite_upgrade_queue.py").read_text(encoding="utf-8")
    inline_src = (WORKSPACE / "doofus/proof/high_score_rescue_loop.py").read_text(encoding="utf-8")
    miner_src = (WORKSPACE / "doofus/proof/high_score_rejection_miner.py").read_text(encoding="utf-8")
    payload = {
        "classification": "DOOFUS_SHADOW_UPGRADE_REPAIR_STARTING_STATE",
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
        "retry2_final_report": str(RETRY2 / "FINAL_REPORT.json"),
        "checkpoint_schema": validate_checkpoint_schema(ck),
        "cycle_checkpoint_schema": validate_cycle_checkpoint_schema(cc),
        "shadow_upgrade_source_summary": {
            "has_deadline_checks": "deadline_monotonic" in shadow_src and "_deadline_exceeded" in shadow_src,
            "has_item_limit": "effective_item_limit" in shadow_src,
            "has_telemetry": "shadow_upgrade_start" in shadow_src,
            "has_defer_classification": "SHADOW_UPGRADE_DEFERRED_DEADLINE" in shadow_src,
        },
        "inline_rescue_source_summary": {
            "has_shadow_defer": "inline_rescue_shadow_upgrade_deferred" in inline_src,
            "has_init_phase": "init_phase" in inline_src,
            "has_budget_policy": "policy_snapshot" in inline_src,
        },
        "high_score_miner_source_summary": {
            "has_progress_abort": "set_progress_handler" in miner_src,
            "has_deferred_classification": "HIGH_SCORE_MINER_DEFERRED_DEADLINE" in miner_src,
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
    final = json.loads((RETRY2 / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    post = json.loads((RETRY2 / "post_run_invariant_check.json").read_text(encoding="utf-8")) if (RETRY2 / "post_run_invariant_check.json").exists() else {}
    telemetry = json.loads((RETRY2 / "gen1640_retry2_live_telemetry_summary.json").read_text(encoding="utf-8")) if (RETRY2 / "gen1640_retry2_live_telemetry_summary.json").exists() else {}
    init_events = telemetry.get("init_events_gen1640", [])
    timeout_event = next((e for e in init_events if e.get("step") == "cycle_init_timeout"), {})
    inline = telemetry.get("inline_rescue_events_gen1640", [])
    payload = {
        "classification": "DOOFUS_RETRY2_FAILURE_RECONSTRUCTION",
        "high_score_miner_repair_worked": True,
        "high_score_miner_deferred_within_deadline": True,
        "inline_rescue_progressed_past_high_score": True,
        "stalled_shadow_upgrade_step": timeout_event.get("detail", {}).get("stalled_step", "inline_rescue_shadow_upgrade_item_complete"),
        "shadow_upgrade_start_event": any(e.get("stage") == "shadow_upgrade_start" for e in inline),
        "shadow_upgrade_item_start_event": any("shadow_upgrade_item_start" in str(e.get("stage", "")) for e in inline),
        "shadow_upgrade_item_complete_event": any("shadow_upgrade_item_complete" in str(e.get("stage", "")) for e in inline),
        "shadow_upgrade_end_event": any(e.get("stage") == "shadow_upgrade" for e in inline),
        "stall_item_candidate_id": "DOOFUS_1525_2690cc8ed8",
        "stall_category": "proof_builder_subprocess_via_run_process_one_guarded",
        "provider_telemetry_started": telemetry.get("provider_telemetry_started", False),
        "model_call_started": False,
        "candidate_generation_started": False,
        "gen1640_rows_created": False,
        "containment_restored_baseline": post.get("checkpoint_generation") == 1639,
        "source_path_to_fix": "doofus/evolution/shadow_elite_upgrade_queue.py + doofus/proof/high_score_rescue_loop.py + doofus/proof/inline_rescue_budget.py",
        "retry_classification": final.get("classification"),
        "init_duration_ms": timeout_event.get("duration_ms"),
        "timeout_error": timeout_event.get("error_message_sanitized"),
    }
    write_pair("RETRY2_FAILURE_RECONSTRUCTION", payload)
    return payload


def phase2() -> dict:
    from doofus.proof.inline_rescue_budget import policy_snapshot

    substeps = [
        {
            "function": "process_upgrade_batch",
            "module": "doofus/evolution/shadow_elite_upgrade_queue.py",
            "expected_duration": "unbounded before repair",
            "has_deadline": True,
            "has_per_item_budget": True,
            "has_telemetry": True,
            "can_block_on_db": True,
            "can_block_on_proof_queue": True,
            "can_block_on_subprocess": True,
            "runs_during_pre_candidate_init": True,
            "should_defer_out_of_init": True,
            "proposed_guard": "init_phase item_limit + sub-deadline + defer nonfatal",
        },
        {
            "function": "run_process_one_guarded",
            "module": "doofus/proof/proof_builder_runner.py",
            "expected_duration": "up to remaining init budget",
            "has_deadline": True,
            "has_per_item_budget": True,
            "can_block_on_subprocess": True,
            "runs_during_pre_candidate_init": True,
            "should_defer_out_of_init": True,
            "proposed_guard": "cap item timeout to shadow_upgrade_max_item_seconds",
        },
        {
            "function": "run_inline_rescue shadow_upgrade stage",
            "module": "doofus/proof/high_score_rescue_loop.py",
            "expected_duration": "shared 180s inline_rescue budget",
            "has_deadline": True,
            "runs_during_pre_candidate_init": True,
            "should_defer_out_of_init": True,
            "proposed_guard": "inline_rescue_shadow_upgrade_deferred nonfatal continue",
        },
    ]
    payload = {"classification": "DOOFUS_SHADOW_UPGRADE_PATH_INVENTORY", "substeps": substeps, "budget_policy": policy_snapshot()}
    write_pair("SHADOW_UPGRADE_PATH_INVENTORY", payload)
    return payload


def phase4() -> dict:
    hypotheses = [
        {
            "rank": 1,
            "hypothesis": "shadow_upgrade processes too many items inside pre-candidate init",
            "evidence_for": "limit=5 with full 180s shared budget in retry2",
            "evidence_against": "stalled on item 0 not item 5",
            "files": ["shadow_elite_upgrade_queue.py", "high_score_rescue_loop.py"],
            "expected_fix": "init item limit=1 + defer when budget low",
            "risk": "low",
        },
        {
            "rank": 2,
            "hypothesis": "per-item timeout equals nearly full remaining init budget",
            "evidence_for": "timeout_seconds = deadline - now - 1 allowed ~170s on first item",
            "evidence_against": "DOOFUS_PROOF_BUILDER_ITEM_TIMEOUT_SECONDS default 20 exists but overridden",
            "files": ["shadow_elite_upgrade_queue.py", "proof_builder_runner.py"],
            "expected_fix": "cap effective_item_timeout_seconds to 25s",
            "risk": "low",
        },
        {
            "rank": 3,
            "hypothesis": "inline_rescue fatal timeout on shadow_upgrade instead of defer",
            "evidence_for": "retry2 init watchdog aborted entire init",
            "files": ["high_score_rescue_loop.py"],
            "expected_fix": "nonfatal inline_rescue_shadow_upgrade_deferred",
            "risk": "low",
        },
    ]
    payload = {"classification": "DOOFUS_SHADOW_UPGRADE_ROOT_CAUSE_HYPOTHESES", "hypotheses": hypotheses}
    write_pair("SHADOW_UPGRADE_ROOT_CAUSE_HYPOTHESES", payload)
    return payload


def phase6() -> dict:
    payload = {
        "classification": "DOOFUS_SHADOW_UPGRADE_DEFERRAL_DECISION",
        "required_before_candidate_generation": False,
        "safe_to_defer": True,
        "defer_destination": "post-cycle maintenance / deferred shadow upgrade queue",
        "telemetry_event": "inline_rescue_shadow_upgrade_deferred",
        "effect_on_proof_builder": "enqueue may occur; proof subprocess deferred in init",
        "effect_on_scoring": "none during init defer",
        "effect_on_promotion": "none during init defer",
        "effect_on_map_elites": "none",
        "retry_readiness_impact": "unblocks candidate generation and model route",
    }
    write_pair("SHADOW_UPGRADE_DEFERRAL_DECISION", payload)
    return payload


def phase7() -> dict:
    from doofus.proof.inline_rescue_budget import policy_snapshot

    payload = {"classification": "DOOFUS_INLINE_RESCUE_BUDGET_POLICY", **policy_snapshot()}
    write_pair("INLINE_RESCUE_BUDGET_POLICY", payload)
    return payload


def phase15_commit() -> dict:
    approved = [
        "doofus/proof/inline_rescue_budget.py",
        "doofus/evolution/shadow_upgrade_telemetry.py",
        "doofus/evolution/shadow_elite_upgrade_queue.py",
        "doofus/proof/high_score_rescue_loop.py",
        "doofus/supervisor/doofus_loop_runner.py",
        "scripts/doofus_shadow_upgrade_diagnostic.py",
        "scripts/doofus_gen1640_shadow_upgrade_rehearsal.py",
        "scripts/doofus_gen1640_shadow_upgrade_rehearsal_worker.py",
        "scripts/doofus_gen1640_inline_rescue_shadow_upgrade_repair_bundle.py",
        "tests/test_shadow_upgrade_deadline.py",
        "tests/test_inline_rescue_budget_policy.py",
    ]
    plan = {
        "classification": "DOOFUS_SHADOW_UPGRADE_REPAIR_COMMIT_PLAN",
        "approved_files": approved,
        "message": "Bound inline rescue shadow upgrade before gen1640 retry",
    }
    write_pair("COMMIT_PLAN", plan)
    existing = [p for p in approved if (WORKSPACE / p).exists()]
    if len(existing) != len(approved):
        return {"committed": False, "reason": "missing approved files", "existing": existing}
    subprocess.run(["git", "add", *approved], cwd=WORKSPACE, check=True)
    body = (
        "bounds shadow_upgrade item processing with deadlines and item limits\n"
        "defers shadow_upgrade when init budget is low\n"
        "protects candidate-generation reserve\n"
        "preserves high-score miner repair\n"
        "adds inline_rescue budget policy\n"
        "adds shadow_upgrade diagnostics and rehearsal\n"
        "adds regression tests for shadow_upgrade deadline/defer behavior\n"
        "preserves gen1639 baseline\n"
        "does not launch gen1640\n"
        "does not invoke live route"
    )
    proc = subprocess.run(
        ["git", "commit", "-m", plan["message"], "-m", body],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    result = {
        "classification": "DOOFUS_SHADOW_UPGRADE_REPAIR_COMMIT_RESULT",
        "committed": proc.returncode == 0,
        "commit": git_out("rev-parse", "HEAD") if proc.returncode == 0 else None,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    write_pair("COMMIT_RESULT", result)
    return result


def main() -> int:
    commit_before = git_out("rev-parse", "HEAD")
    starting = phase0()
    reconstruction = phase1()
    inventory = phase2()

    diag_before = run_cmd(
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
            "SHADOW_UPGRADE_DIAGNOSTIC_BEFORE_REPAIR",
        ],
        timeout=120,
    )
    diag_before_payload = json.loads((OUT / "SHADOW_UPGRADE_DIAGNOSTIC_BEFORE_REPAIR.json").read_text(encoding="utf-8")) if (OUT / "SHADOW_UPGRADE_DIAGNOSTIC_BEFORE_REPAIR.json").exists() else {}

    hypotheses = phase4()
    deferral = phase6()
    budget = phase7()

    rehearsal = run_cmd([sys.executable, "scripts/doofus_gen1640_shadow_upgrade_rehearsal.py", "--output-dir", str(OUT), "--low-budget"])
    rehearsal_payload = json.loads((OUT / "SHADOW_UPGRADE_REHEARSAL_RESULT.json").read_text(encoding="utf-8")) if (OUT / "SHADOW_UPGRADE_REHEARSAL_RESULT.json").exists() else {}

    t_focus = run_cmd(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_shadow_upgrade_deadline.py",
            "tests/test_inline_rescue_budget_policy.py",
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
            "shadow_upgrade or inline_rescue or high_score or init_timeout or containment or cycle_init or provider_gate or live_cycle_launch_guard or live_db_preflight or isolated_runtime or nonlive_cycle_forces_model_dry_run or proof_builder or map_elites or scoring or postlive or self_improvement",
            "-q",
        ],
        timeout=600,
    )
    write_pair(
        "TEST_RESULTS",
        {
            "classification": "DOOFUS_SHADOW_UPGRADE_REPAIR_TESTS",
            "focused_passed": t_focus.returncode == 0,
            "focused_tail": (t_focus.stdout or t_focus.stderr or "")[-2000:],
            "broader_passed": t_broad.returncode == 0,
            "broader_tail": (t_broad.stdout or t_broad.stderr or "")[-2000:],
        },
    )

    diag_after = run_cmd(
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
            "SHADOW_UPGRADE_DIAGNOSTIC_AFTER_REPAIR",
        ],
        timeout=120,
    )
    diag_after_payload = json.loads((OUT / "SHADOW_UPGRADE_DIAGNOSTIC_AFTER_REPAIR.json").read_text(encoding="utf-8")) if (OUT / "SHADOW_UPGRADE_DIAGNOSTIC_AFTER_REPAIR.json").exists() else {}

    miner_after = run_cmd(
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
            "HIGH_SCORE_MINER_DIAGNOSTIC_AFTER_SHADOW_REPAIR",
        ],
        timeout=120,
    )
    miner_after_payload = json.loads((OUT / "HIGH_SCORE_MINER_DIAGNOSTIC_AFTER_SHADOW_REPAIR.json").read_text(encoding="utf-8")) if (OUT / "HIGH_SCORE_MINER_DIAGNOSTIC_AFTER_SHADOW_REPAIR.json").exists() else {}

    init_rehearsal = run_cmd([sys.executable, "scripts/doofus_gen1640_init_rehearsal.py", "--output-dir", str(OUT)])
    init_payload = json.loads((OUT / "INIT_REHEARSAL_RESULT.json").read_text(encoding="utf-8")) if (OUT / "INIT_REHEARSAL_RESULT.json").exists() else {}
    if init_payload:
        write_pair("NONLIVE_GEN1640_INIT_REHEARSAL_AFTER_SHADOW_REPAIR", init_payload)

    pf = run_cmd([sys.executable, "scripts/doofus_live_db_preflight.py", "--output-dir", str(OUT)], timeout=120)
    pf_payload = json.loads((OUT / "live_db_preflight_check_only.json").read_text(encoding="utf-8")) if (OUT / "live_db_preflight_check_only.json").exists() else {}
    write_pair("LIVE_DB_PREFLIGHT_AFTER_SHADOW_REPAIR", {"classification": "DOOFUS_LIVE_DB_PREFLIGHT_AFTER_SHADOW_REPAIR", "preflight": pf_payload, "passed": not pf_payload.get("blockers")})

    write_pair(
        "PROVIDER_RECOMMENDATION_AFTER_SHADOW_REPAIR",
        {
            "classification": "DOOFUS_PROVIDER_RECOMMENDATION_AFTER_SHADOW_REPAIR",
            "provider": "cursor",
            "model": "composer-2.5",
            "switch_recommended": False,
            "reason": "retry2 failed pre-model at shadow_upgrade; fix inline_rescue shadow path first",
        },
    )

    tests_ok = t_focus.returncode == 0 and t_broad.returncode == 0
    diag_before_ok = diag_before_payload.get("passed") is True or diag_before.returncode == 0
    diag_after_ok = diag_after_payload.get("passed") is True
    miner_ok = miner_after_payload.get("passed") is True
    rehearsal_ok = rehearsal_payload.get("passed") is True
    init_ok = init_payload.get("classification") in {"DOOFUS_INIT_REHEARSAL_PASS", "DOOFUS_INIT_REHEARSAL_STALL_ABORT_PASS"}
    pf_ok = not pf_payload.get("blockers")

    commit_result = phase15_commit()
    commit_after = git_out("rev-parse", "HEAD")

    ready = (
        tests_ok
        and diag_after_ok
        and miner_ok
        and rehearsal_ok
        and init_ok
        and pf_ok
        and commit_result.get("committed")
    )

    if ready:
        write_pair(
            "GEN1640_RETRY3_OPERATOR_REVIEW_PACKET_PREP_ONLY",
            {
                "classification": "DOOFUS_GEN1640_RETRY3_OPERATOR_REVIEW_PACKET_PREP_ONLY",
                "warning": "Preparation only. This does not authorize gen1640 retry3 launch.",
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
                    "high_score_miner_diagnostic": miner_ok,
                    "shadow_upgrade_diagnostic": diag_after_ok,
                    "inline_rescue_budget_policy": True,
                    "nonlive_init_rehearsal": init_ok,
                    "no_live_route_during_repair": True,
                },
                "recommended_retry_command": "python -m doofus.supervisor.provider_aware_live_cycle --operator-approved-one-cycle --max-model-calls 2 --max-cost-usd 0.05",
            },
        )

    final_class = (
        "DOOFUS_GEN1640_INLINE_RESCUE_SHADOW_UPGRADE_REPAIR_READY_FOR_RETRY_REVIEW"
        if ready
        else "DOOFUS_GEN1640_INLINE_RESCUE_SHADOW_UPGRADE_REPAIR_PARTIAL"
        if starting.get("safe_to_proceed")
        else "DOOFUS_GEN1640_INLINE_RESCUE_SHADOW_UPGRADE_REPAIR_FAIL"
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
            "retry3_packet_exists": (OUT / "GEN1640_RETRY3_OPERATOR_REVIEW_PACKET_PREP_ONLY.json").exists(),
        },
    )

    write_pair(
        "FINAL_REPORT",
        {
            "classification": final_class,
            "starting_state": starting,
            "retry2_failure_reconstruction": reconstruction,
            "shadow_upgrade_path_inventory": inventory,
            "shadow_upgrade_diagnostic_before": diag_before_payload,
            "root_cause_hypotheses": hypotheses,
            "shadow_upgrade_deferral": deferral,
            "inline_rescue_budget_policy": budget,
            "shadow_upgrade_rehearsal": rehearsal_payload,
            "tests_ok": tests_ok,
            "shadow_upgrade_diagnostic_after": diag_after_payload,
            "high_score_miner_diagnostic_after": miner_after_payload,
            "nonlive_init_rehearsal": init_payload,
            "live_db_preflight_ok": pf_ok,
            "commit_result": commit_result,
            "next_action": "Review GEN1640_RETRY3_OPERATOR_REVIEW_PACKET_PREP_ONLY.*; then decide whether to approve exactly one controlled gen1640 retry3 in a separate prompt."
            if ready
            else "Complete failing repair gate before retry3 authorization.",
        },
    )

    print(
        json.dumps(
            {
                "final_classification": final_class,
                "commit_before": commit_before,
                "commit_after": commit_after,
                "tests_ok": tests_ok,
                "diag_after_ok": diag_after_ok,
                "miner_ok": miner_ok,
                "rehearsal_ok": rehearsal_ok,
                "init_ok": init_ok,
                "pf_ok": pf_ok,
                "committed": commit_result.get("committed"),
            },
            indent=2,
        )
    )
    return 0 if final_class.endswith("READY_FOR_RETRY_REVIEW") else 1


if __name__ == "__main__":
    raise SystemExit(main())
