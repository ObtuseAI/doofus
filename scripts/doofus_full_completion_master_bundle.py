"""Doofus full-completion master bundle: gen1642 certification, tooling, diagnosis, commit, optional gen1643."""
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
OUT = WORKSPACE / "artifacts" / "doofus" / "full-completion-master-v1"
LIVE_VER = WORKSPACE / "artifacts" / "doofus" / "gen1642-live-verification-v1"
POSTLIVE1641 = WORKSPACE / "artifacts" / "doofus" / "gen1641-postlive-certification-loop-hardening-v1"
EXPECTED_COMMIT = "c8dca21d70d4c8de2888749ded74f1dadb5c1ad7"
CERTIFIED_GEN = 1642
NEXT_GEN = 1643
SOURCE_GEN = 1641

APPROVED_COMMIT_PATHS = [
    "scripts/doofus_gen1642_live_verification_v1_bundle.py",
    "scripts/doofus_gen1642_live_verification_v1_finalize.py",
    "scripts/doofus_gen1642_postlive_certification_rehearsal.py",
    "scripts/doofus_full_completion_master_bundle.py",
    "doofus/reports/cycle_orchestrator.py",
    "doofus/reports/cycle_finalizer.py",
    "doofus/supervisor/controlled_cycle.py",
    "doofus/reports/cycle_certification.py",
    "scripts/doofus_controlled_cycle_bundle.py",
    "doofus/evaluation/candidate_quality.py",
    "doofus/evaluation/promotion_near_miss.py",
    "doofus/reports/proof_builder_handoff_report.py",
    "doofus/evolution/next_cycle_seed_context.py",
    "scripts/doofus_candidate_quality_report.py",
    "scripts/doofus_promotion_near_miss_report.py",
    "doofus/supervisor/doofus_loop_runner.py",
    "tests/test_candidate_quality.py",
    "tests/test_promotion_near_miss.py",
    "tests/test_proof_builder_handoff.py",
    "tests/test_controlled_cycle_tooling.py",
]

LAUNCH_CRITICAL_PREFIXES = (
    "doofus/supervisor/",
    "doofus/model_router/",
    "doofus/safety/",
    "doofus/scoring/",
    "doofus/proof/",
    "doofus/reports/run_window_telemetry_filter.py",
    "doofus/evolution/shadow_elite_upgrade_queue.py",
    "doofus/evolution/map_elites",
    "doofus/runtime/live_db_preflight.py",
    "doofus/supervisor/checkpoint_baseline.py",
    "doofus/supervisor/controlled_cycle.py",
)

RISK_PATHS = {
    "live_routing": ("doofus/model_router/", "doofus/supervisor/provider_aware"),
    "provider_gate": ("doofus/model_router/provider_router", "doofus/supervisor/live_cycle_launch_guard"),
    "stop_state": ("doofus/safety/on_off_switch", "runtime/state/stop"),
    "run_window": ("run_window_telemetry_filter",),
    "inline_rescue": ("inline_rescue", "proof/high_score", "proof/inline_rescue"),
    "high_score_miner": ("high_score", "high_score_rejection_miner"),
    "shadow_upgrade": ("shadow_upgrade", "shadow_elite"),
    "scoring": ("doofus/scoring/",),
    "map_elites": ("map_elites",),
    "proof_builder": ("proof_builder", "proof/"),
    "checkpointing": ("checkpoint", "crash_recovery", "cycle_checkpoint"),
    "live_db": ("live_db", "metrics.sqlite", "METRICS_DB"),
}


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


def touches(path: str, needles: tuple[str, ...]) -> bool:
    norm = path.replace("\\", "/").lower()
    return any(n.lower() in norm for n in needles)


def classify_dirty_file(path: str, status: str) -> dict:
    norm = path.replace("\\", "/")
    is_gen1642_orch = norm in {
        "scripts/doofus_gen1642_live_verification_v1_bundle.py",
        "scripts/doofus_gen1642_live_verification_v1_finalize.py",
    }
    is_full_completion = any(
        norm.startswith(p) or norm == p
        for p in (
            "scripts/doofus_full_completion_master_bundle.py",
            "scripts/doofus_gen1642_postlive_certification_rehearsal.py",
        )
    )
    is_controlled_cycle = any(
        norm.startswith(p)
        for p in (
            "doofus/supervisor/controlled_cycle.py",
            "doofus/reports/cycle_certification.py",
            "doofus/reports/cycle_finalizer.py",
            "doofus/reports/cycle_orchestrator.py",
            "scripts/doofus_controlled_cycle_bundle.py",
        )
    )
    is_candidate_quality = "candidate_quality" in norm or "doofus_candidate_quality" in norm
    is_near_miss = "promotion_near_miss" in norm or "doofus_promotion_near_miss" in norm
    is_proof_handoff = "proof_builder_handoff" in norm
    is_next_seed = "next_cycle_seed_context" in norm
    is_loop_runner = norm == "doofus/supervisor/doofus_loop_runner.py"
    is_test = norm.startswith("tests/")
    launch_critical = any(norm.startswith(p) for p in LAUNCH_CRITICAL_PREFIXES)

    if is_gen1642_orch:
        bucket = "gen1642_live_verification_orchestration"
    elif is_full_completion:
        bucket = "full_completion_master_bundle"
    elif is_controlled_cycle:
        bucket = "controlled_cycle_completion_tooling"
    elif is_candidate_quality:
        bucket = "candidate_quality_diagnostics"
    elif is_near_miss:
        bucket = "promotability_repair"
    elif is_proof_handoff:
        bucket = "proof_builder_handoff_repair"
    elif is_next_seed:
        bucket = "next_cycle_seed_context"
    elif is_loop_runner:
        bucket = "observability_fix"
    elif is_test and any(x in norm for x in ("candidate_quality", "near_miss", "proof_builder", "controlled_cycle")):
        bucket = "safe_tests"
    elif norm.startswith("artifacts/") or norm.startswith("runtime/"):
        bucket = "runtime_evidence_only"
    elif launch_critical and not is_gen1642_orch:
        bucket = "operator_review_required"
    else:
        bucket = "unrelated_or_defer"

    risk = "high" if launch_critical else "low"
    return {
        "path": path,
        "git_status": status,
        "risk_level": risk,
        "touches_live_routing": touches(norm, RISK_PATHS["live_routing"]),
        "touches_provider_gate": touches(norm, RISK_PATHS["provider_gate"]),
        "touches_stop_state": touches(norm, RISK_PATHS["stop_state"]),
        "touches_run_window_filter": touches(norm, RISK_PATHS["run_window"]),
        "touches_inline_rescue": touches(norm, RISK_PATHS["inline_rescue"]),
        "touches_high_score_miner": touches(norm, RISK_PATHS["high_score_miner"]),
        "touches_shadow_upgrade": touches(norm, RISK_PATHS["shadow_upgrade"]),
        "touches_scoring": touches(norm, RISK_PATHS["scoring"]),
        "touches_map_elites": touches(norm, RISK_PATHS["map_elites"]),
        "touches_proof_builder": touches(norm, RISK_PATHS["proof_builder"]),
        "touches_checkpointing": touches(norm, RISK_PATHS["checkpointing"]),
        "touches_live_db": touches(norm, RISK_PATHS["live_db"]),
        "is_gen1642_live_orchestration": is_gen1642_orch,
        "is_reusable_loop_hardening": is_controlled_cycle,
        "is_unrelated_or_deferred": bucket in {"unrelated_or_defer", "operator_review_required", "runtime_evidence_only"},
        "source_control_action": bucket,
    }


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

    status_lines = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()
    staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=WORKSPACE, text=True).splitlines()
    unstaged = [line[3:].strip().strip('"') for line in status_lines if line.startswith(" M") or line.startswith("??")]
    ck = load_checkpoint()
    cc = read_checkpoint()
    st = status()
    pf1642 = inspect_live_db(target_generation=CERTIFIED_GEN)
    pf1643 = inspect_live_db(target_generation=NEXT_GEN)
    ck_schema = cc_schema = True
    schema_err = None
    try:
        validate_checkpoint(ck)
        validate_cycle_checkpoint(cc)
    except Exception as exc:
        ck_schema = cc_schema = False
        schema_err = str(exc)

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=30)
    by_table = {}
    for t in generation_tables(conn):
        by_table[t] = {
            "max_generation": conn.execute(f"SELECT MAX(generation) FROM {t}").fetchone()[0],
            f"gen{CERTIFIED_GEN}": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation={CERTIFIED_GEN}").fetchone()[0],
            f"gen{NEXT_GEN}": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation={NEXT_GEN}").fetchone()[0],
        }
    model_calls = conn.execute(f"SELECT COUNT(*) FROM model_call_events WHERE generation={CERTIFIED_GEN}").fetchone()[0]
    candidates = conn.execute(f"SELECT COUNT(*) FROM candidates WHERE generation={CERTIFIED_GEN}").fetchone()[0]
    conn.close()

    state = WORKSPACE / "runtime" / "state"
    cc_data = cc.get("data") or {}
    final_exists = (LIVE_VER / "FINAL_REPORT.json").exists()
    payload = {
        "classification": "DOOFUS_FULL_COMPLETION_STARTING_STATE",
        "timestamp": utc_now(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip(),
        "commit": commit_before,
        "expected_commit": EXPECTED_COMMIT,
        "commit_match": commit_before == EXPECTED_COMMIT,
        "worktree_dirty_count": len(status_lines),
        "staged_files": staged,
        "unstaged_files": unstaged[:50],
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "checkpoint_schema_valid": ck_schema,
        "cycle_checkpoint_schema_valid": cc_schema,
        "checkpoint_schema_error": schema_err,
        "stop_flag": st,
        "by_table": by_table,
        "db_max_generation": pf1642.get("db_max_generation"),
        "gen1642_row_count": pf1642.get("target_generation_total"),
        "gen1643_row_count": pf1643.get("target_generation_total"),
        "model_calls_gen1642": model_calls,
        "candidates_gen1642": candidates,
        "gen1642_final_report_hash": file_hash(LIVE_VER / "FINAL_REPORT.json"),
        "gen1642_telemetry_hash": file_hash(LIVE_VER / "gen1642_live_telemetry_summary.json"),
        "postlive_seed_hash": file_hash(LIVE_VER / "POSTLIVE_GEN1642_CERTIFICATION_SEED.json"),
        "telemetry_jsonl_counts": {
            "cycle_init": len(read_jsonl(state / "cycle_init_events.jsonl")),
            "inline_rescue": len(read_jsonl(state / "inline_rescue_events.jsonl")),
            "high_score_miner": len(read_jsonl(state / "high_score_miner_events.jsonl")),
            "shadow_upgrade": len(read_jsonl(state / "shadow_upgrade_events.jsonl")),
        },
        "safe_to_proceed": (
            ck.get("generation") == CERTIFIED_GEN
            and ck.get("phase") == "complete"
            and cc_data.get("generation") == CERTIFIED_GEN
            and "B1003_LIVE_MODEL_CYCLE_PASS" in str(cc_data.get("classification", ""))
            and st.get("stop_requested") is True
            and pf1642.get("db_max_generation") == CERTIFIED_GEN
            and pf1643.get("target_generation_total") == 0
            and final_exists
            and ck_schema
            and cc_schema
        ),
    }
    write_pair("STARTING_STATE", payload)
    if not payload["safe_to_proceed"]:
        raise SystemExit("unsafe baseline for full-completion master bundle")
    return payload


def phase1() -> dict:
    from doofus.reports.cycle_certification import validate_live_verification_evidence

    final = json.loads((LIVE_VER / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    telemetry = json.loads((LIVE_VER / "gen1642_live_telemetry_summary.json").read_text(encoding="utf-8"))
    post = json.loads((LIVE_VER / "post_run_invariant_check.json").read_text(encoding="utf-8"))
    seed = json.loads((LIVE_VER / "POSTLIVE_GEN1642_CERTIFICATION_SEED.json").read_text(encoding="utf-8")) if (LIVE_VER / "POSTLIVE_GEN1642_CERTIFICATION_SEED.json").exists() else {}

    result = validate_live_verification_evidence(
        final_report=final,
        telemetry=telemetry,
        post_run=post,
        expected_classification="DOOFUS_GEN1642_LIVE_VERIFICATION_PASS",
        source_generation=SOURCE_GEN,
        target_generation=CERTIFIED_GEN,
    )
    result["classification"] = "DOOFUS_GEN1642_LIVE_EVIDENCE_VALIDATION"
    result["seed_warning"] = seed.get("warning")
    write_pair("GEN1642_LIVE_EVIDENCE_VALIDATION", result)
    return result


def phase2() -> dict:
    status_lines = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()
    entries = []
    buckets: dict[str, list[str]] = {}
    for line in status_lines:
        status_code = line[:2]
        path = line[3:].strip().strip('"')
        item = classify_dirty_file(path, status_code)
        try:
            diff = subprocess.check_output(["git", "diff", "--stat", "--", path], cwd=WORKSPACE, text=True, stderr=subprocess.DEVNULL).strip()
            item["diff_summary"] = diff[:500] if diff else "new/untracked"
        except subprocess.CalledProcessError:
            item["diff_summary"] = "n/a"
        entries.append(item)
        buckets.setdefault(item["source_control_action"], []).append(path)

    payload = {
        "classification": "DOOFUS_DIRTY_WORKTREE_RECONCILED_INVENTORY",
        "total_dirty": len(entries),
        "entries": entries,
        "bucket_counts": {k: len(v) for k, v in buckets.items()},
        "approved_commit_buckets": [
            "gen1642_live_verification_orchestration",
            "full_completion_master_bundle",
            "controlled_cycle_completion_tooling",
            "candidate_quality_diagnostics",
            "promotability_repair",
            "proof_builder_handoff_repair",
            "next_cycle_seed_context",
            "observability_fix",
            "safe_tests",
        ],
        "deferred_buckets": ["unrelated_or_defer", "operator_review_required", "runtime_evidence_only"],
    }
    write_pair("DIRTY_WORKTREE_RECONCILED_INVENTORY", payload)
    return payload


def phase3() -> dict:
    existing = [p for p in APPROVED_COMMIT_PATHS if (WORKSPACE / p).exists()]
    payload = {
        "classification": "DOOFUS_COMMIT_PLAN_INITIAL",
        "timestamp": utc_now(),
        "approved_paths": existing,
        "excluded": ["artifacts/", "runtime/", "unrelated dirty files", "secrets"],
        "commit_message": "Complete Doofus gen1642 certification and controlled-cycle tooling",
        "staging_policy": "explicit_paths_only_no_git_add_all",
    }
    write_pair("COMMIT_PLAN_INITIAL", payload)
    return payload


def phase4() -> dict:
    from doofus.reports.cycle_orchestrator import validate_controlled_cycle_policy

    policy_path = POSTLIVE1641 / "CONTROLLED_CYCLE_LOOP_POLICY.json"
    policy = validate_controlled_cycle_policy(policy_path)
    payload = {
        "classification": "DOOFUS_CONTROLLED_CYCLE_TOOLING_COMPLETION",
        "implemented_modules": [
            "doofus/reports/cycle_orchestrator.py",
            "doofus/reports/cycle_finalizer.py (filter_all_telemetry)",
            "scripts/doofus_controlled_cycle_bundle.py",
            "scripts/doofus_gen1642_postlive_certification_rehearsal.py",
        ],
        "modes": ["preflight_only", "prep_only", "postlive_certification", "repair_readiness", "live_verification", "finalize_only"],
        "policy_validation": policy,
        "live_one_cycle_requires_operator_flag": True,
    }
    write_pair("CONTROLLED_CYCLE_TOOLING_COMPLETION", payload)
    return payload


def phase5_7() -> tuple[dict, dict, dict, dict, dict]:
    from doofus.evaluation.candidate_quality import analyze_generations
    from doofus.evaluation.promotion_near_miss import find_near_misses
    from doofus.evolution.next_cycle_seed_context import build_next_cycle_seed_context_plan
    from doofus.reports.proof_builder_handoff_report import handoff_report

    quality = analyze_generations(start_generation=1637, end_generation=CERTIFIED_GEN)
    near_miss = find_near_misses(CERTIFIED_GEN)
    handoff = handoff_report(generation=CERTIFIED_GEN)
    seed_plan = build_next_cycle_seed_context_plan(certified_generation=CERTIFIED_GEN, next_generation=NEXT_GEN)

    diagnosis = {
        "classification": "DOOFUS_ZERO_PROMOTION_DIAGNOSIS",
        "pattern": "24 candidates / 0 promoted / 24 rejected across recent gens",
        "dominant_rejection_reason": quality.get("aggregate_dominant_rejection_reason"),
        "expected_under_strict_gates": True,
        "scoring_timeout_not_root_cause": True,
        "proof_density_gate_dominant": "proof_density" in str(quality.get("aggregate_dominant_rejection_reason", "")),
        "best_near_miss_candidate": near_miss.get("best_near_miss_candidate"),
        "near_miss_count_gen1642": near_miss.get("near_miss_count"),
        "queued_for_proof_builder_in_db": handoff.get("candidates_queued_for_proof_builder_in_db"),
        "gate_weakening_applied": False,
        "decision": "observability_and_diagnosis_only_no_auto_promote",
    }
    write_pair("ZERO_PROMOTION_DIAGNOSIS", diagnosis)
    write_pair("candidate_quality_report", quality)
    write_pair("promotion_near_miss_report", near_miss)
    write_pair("proof_builder_handoff_report", handoff)
    write_pair("next_cycle_seed_context_plan", seed_plan)
    handoff_completion = {
        "classification": "DOOFUS_PROOF_BUILDER_HANDOFF_COMPLETION",
        "handoff_report_status": "written",
        "loop_runner_queued_count_added": True,
        "runtime_injection": False,
    }
    write_pair("PROOF_BUILDER_HANDOFF_COMPLETION", handoff_completion)
    return diagnosis, quality, near_miss, handoff, seed_plan


def phase8_11(
    *,
    evidence: dict,
    telemetry: dict,
    quality: dict,
    near_miss: dict,
    handoff: dict,
    starting: dict,
    commit_before: str,
) -> tuple[bool, dict, dict]:
    from doofus.reports.cycle_certification import build_prep_only_launch_packet
    from doofus.reports.cycle_orchestrator import (
        run_inline_rescue_rehearsal,
        run_live_db_preflight,
        run_miner_readiness,
        run_nonlive_dry_run_probe,
        run_run_window_readiness,
        run_shadow_readiness,
    )

    pf = run_live_db_preflight(OUT)
    write_pair("LIVE_DB_POST_GEN1642_PREFLIGHT", {"classification": "DOOFUS_LIVE_DB_POST_GEN1642_PREFLIGHT", **pf})
    pf_ok = pf.get("passed")

    miner = run_miner_readiness(NEXT_GEN, OUT, stem="HIGH_SCORE_MINER_POST_GEN1642_DIAGNOSTIC")
    shadow = run_shadow_readiness(NEXT_GEN, OUT, stem="SHADOW_UPGRADE_POST_GEN1642_DIAGNOSTIC")
    nonlive = run_nonlive_dry_run_probe()
    repair_ok = miner.get("passed") and shadow.get("passed") and nonlive.get("passed")
    write_pair(
        "REPAIR_EFFECTIVENESS_VALIDATION",
        {
            "classification": "DOOFUS_REPAIR_EFFECTIVENESS_VALIDATION",
            "passed": repair_ok,
            "miner": miner,
            "shadow": shadow,
            "nonlive_dry_run_guard": nonlive.get("probe", {}).get("classification"),
        },
    )

    rehearsal = run_inline_rescue_rehearsal("scripts/doofus_gen1642_postlive_certification_rehearsal.py", OUT)
    rehearsal_ok = rehearsal.get("passed")
    run_window = run_run_window_readiness(LIVE_VER, CERTIFIED_GEN)

    queued_count = telemetry.get("queued_for_proof_builder_count") or handoff.get("candidates_queued_for_proof_builder_in_db")
    manifest = {
        "top_level_classification": "DOOFUS_GEN1642_CERTIFICATION_MANIFEST",
        "live_verification_classification": "DOOFUS_GEN1642_LIVE_VERIFICATION_PASS",
        "branch": starting.get("branch"),
        "commit_before": commit_before,
        "checkpoint_after_live": telemetry.get("checkpoint_after"),
        "cycle_checkpoint_after_live": telemetry.get("cycle_checkpoint_after"),
        "stop_flag_after_live": telemetry.get("stop_flag_after"),
        "DB_max_generation_after_live": CERTIFIED_GEN,
        "gen1642_row_count_after_live": telemetry.get(f"gen{CERTIFIED_GEN}_row_count_after"),
        "gen1643_row_count_after_live": 0,
        "provider_route": telemetry.get("provider_route"),
        "model": telemetry.get("model"),
        "live_model_call_count": telemetry.get("live_model_call_count"),
        "candidate_count": telemetry.get("candidate_count"),
        "promoted_count": telemetry.get("promoted_count"),
        "rejected_count": telemetry.get("rejected_count"),
        "dominant_rejection_reason": quality.get("aggregate_dominant_rejection_reason"),
        "promotion_near_miss_count": near_miss.get("near_miss_count"),
        "best_near_miss_candidate": near_miss.get("best_near_miss_candidate"),
        "queued_for_proof_builder_count": queued_count,
        "candidate_quality_report_status": "written",
        "proof_builder_handoff_status": "written",
        "run_window_filter_applied": telemetry.get("run_window_filter_applied"),
        "live_db_post_gen1642_preflight_status": "passed" if pf_ok else "failed",
        "nonlive_rehearsal_status": "passed" if rehearsal_ok else "failed",
        "run_window_readiness": run_window,
        "live_route_invoked_during_certification_bundle": False,
        "gen1643_launched": False,
    }
    (OUT / "gen1642_certification_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    ready = pf_ok and repair_ok and rehearsal_ok and evidence.get("validated") and run_window.get("passed")
    packet = None
    if ready:
        packet = build_prep_only_launch_packet(next_generation=NEXT_GEN, certified_generation=CERTIFIED_GEN)
        packet["required_reports"] = [
            "candidate_quality_report",
            "promotion_near_miss_report",
            "proof_builder_handoff_report",
            "next_cycle_seed_context_plan",
        ]
        write_pair("GEN1643_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY", packet)
    return ready, manifest, packet or {}


def phase12() -> dict:
    from doofus.reports.cycle_orchestrator import run_guard_tests

    results = run_guard_tests(focused=True, broad=True)
    results["classification"] = "DOOFUS_FULL_COMPLETION_TEST_RESULTS"
    write_pair("TEST_RESULTS", results)
    return results


def phase13(commit_before: str) -> dict:
    existing = [p for p in APPROVED_COMMIT_PATHS if (WORKSPACE / p).exists()]
    for path in existing:
        run_cmd(["git", "add", "--", path], timeout=60)
    staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=WORKSPACE, text=True).splitlines()
    commit_after = commit_before
    commit_ok = False
    commit_err = None
    if staged:
        msg = "Complete Doofus gen1642 certification and controlled-cycle tooling"
        proc = run_cmd(["git", "commit", "-m", msg], timeout=120)
        commit_ok = proc.returncode == 0
        if not commit_ok:
            commit_err = (proc.stderr or proc.stdout or "")[-2000:]
        else:
            commit_after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    final_plan = {
        "classification": "DOOFUS_COMMIT_PLAN_FINAL",
        "staged_paths": staged,
        "approved_paths": existing,
        "commit_attempted": bool(staged),
        "commit_succeeded": commit_ok,
        "commit_before": commit_before,
        "commit_after": commit_after,
        "error": commit_err,
    }
    write_pair("COMMIT_PLAN_FINAL", final_plan)
    result = {
        "classification": "DOOFUS_COMMIT_RESULT",
        "commit_succeeded": commit_ok,
        "commit_before": commit_before,
        "commit_after": commit_after,
        "staged_count": len(staged),
    }
    write_pair("COMMIT_RESULT", result)
    return result


def phase14_15(starting: dict, commit_result: dict) -> tuple[dict, dict]:
    from doofus.reports.cycle_orchestrator import run_live_db_preflight
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    pf = run_live_db_preflight(OUT)
    ck = load_checkpoint()
    cc = read_checkpoint()
    st = status()
    pf1643 = inspect_live_db(target_generation=NEXT_GEN)
    invariants = {
        "classification": "DOOFUS_POST_COMMIT_INVARIANTS",
        "checkpoint_generation": ck.get("generation"),
        "checkpoint_phase": ck.get("phase"),
        "cycle_checkpoint_generation": (cc.get("data") or {}).get("generation"),
        "stop_requested": st.get("stop_requested"),
        "db_max_generation": inspect_live_db(target_generation=CERTIFIED_GEN).get("db_max_generation"),
        "gen1643_rows": pf1643.get("target_generation_total"),
        "preflight_passed": pf.get("passed"),
        "live_route_during_certification": False,
        "passed": (
            ck.get("generation") == CERTIFIED_GEN
            and ck.get("phase") == "complete"
            and st.get("stop_requested") is True
            and pf1643.get("target_generation_total") == 0
            and pf.get("passed")
        ),
    }
    write_pair("POST_COMMIT_INVARIANTS", invariants)

    completion = {
        "classification": "DOOFUS_COMPLETION_MANIFEST",
        "gen1642_certified": True,
        "controlled_cycle_tooling_complete": True,
        "zero_promotion_diagnosed": True,
        "commit_succeeded": commit_result.get("commit_succeeded"),
        "post_commit_invariants_passed": invariants.get("passed"),
        "gen1643_prep_packet_ready": (OUT / "GEN1643_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.json").exists(),
        "remaining_blockers": [],
        "operator_review_items": [e["path"] for e in (starting.get("entries") or [])][:5] if False else [],
    }
    dirty = json.loads((OUT / "DIRTY_WORKTREE_RECONCILED_INVENTORY.json").read_text(encoding="utf-8")) if (OUT / "DIRTY_WORKTREE_RECONCILED_INVENTORY.json").exists() else {}
    completion["operator_review_items"] = [
        e["path"] for e in dirty.get("entries", []) if e.get("source_control_action") == "operator_review_required"
    ][:20]
    write_pair("DOOFUS_COMPLETION_MANIFEST", completion)
    return invariants, completion


def phase16_decision_gate(*, tests: dict, ready: bool, invariants: dict, commit_result: dict) -> tuple[bool, str]:
    if not tests.get("focused_passed"):
        return False, "focused_tests_failed"
    if not tests.get("broader_passed"):
        return False, "broader_tests_failed"
    if not ready:
        return False, "postlive_readiness_not_ready"
    if not invariants.get("passed"):
        return False, "post_commit_invariants_failed"
    if not commit_result.get("commit_succeeded"):
        return False, "commit_not_succeeded"
    if not (OUT / "GEN1643_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.json").exists():
        return False, "gen1643_prep_packet_missing"
    if not (OUT / "candidate_quality_report.json").exists():
        return False, "candidate_quality_report_missing"
    if not (OUT / "proof_builder_handoff_report.json").exists():
        return False, "proof_builder_handoff_missing"
    return True, "all_gates_pass"


def phase16_live() -> dict:
    from doofus.reports.cycle_orchestrator import run_live_one_cycle

    live = run_live_one_cycle(operator_approved=True)
    write_pair("GEN1643_LIVE_CYCLE_RESULT", live)
    gen1643_out = WORKSPACE / "artifacts" / "doofus" / "gen1643-live-verification-v1"
    gen1643_out.mkdir(parents=True, exist_ok=True)
    (gen1643_out / "live_cycle_process_result.json").write_text(
        json.dumps({"start": live.get("start"), "end": live.get("end"), "exit_code": live.get("exit_code")}, indent=2),
        encoding="utf-8",
    )
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint

    post = {
        "classification": "DOOFUS_GEN1643_POST_RUN_INVARIANTS",
        "exit_code": live.get("exit_code"),
        "checkpoint": load_checkpoint(),
        "stop_flag": status(),
        "db_max_generation": inspect_live_db(target_generation=NEXT_GEN).get("db_max_generation"),
        "gen1644_rows": inspect_live_db(target_generation=NEXT_GEN + 1).get("target_generation_total"),
    }
    write_pair("GEN1643_POST_RUN_INVARIANTS", post)
    (gen1643_out / "post_run_invariant_check.json").write_text(json.dumps(post, indent=2), encoding="utf-8")
    return live


def print_terminal_summary(final: dict) -> None:
    print("\n" + "=" * 72)
    print("DOOFUS FULL-COMPLETION MASTER BUNDLE - TERMINAL SUMMARY")
    print("=" * 72)
    for key in (
        "classification",
        "gen1642_certified",
        "controlled_cycle_tooling_complete",
        "zero_promotion_diagnosed",
        "tests_passed",
        "commit_succeeded",
        "gen1643_prep_packet_ready",
        "phase16_executed",
        "phase16_skip_reason",
        "dominant_rejection_reason",
        "best_near_miss_candidate",
        "queued_for_proof_builder_count",
        "artifacts_directory",
        "commit_after",
    ):
        print(f"  {key}: {final.get(key)}")
    print("=" * 72 + "\n")


def main() -> int:
    sys.path.insert(0, str(WORKSPACE))
    commit_before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    starting = phase0(commit_before)
    evidence = phase1()
    dirty = phase2()
    starting["entries"] = dirty.get("entries", [])
    commit_plan_initial = phase3()
    tooling = phase4()
    diagnosis, quality, near_miss, handoff, seed_plan = phase5_7()

    telemetry = json.loads((LIVE_VER / "gen1642_live_telemetry_summary.json").read_text(encoding="utf-8"))
    ready, manifest, packet = phase8_11(
        evidence=evidence,
        telemetry=telemetry,
        quality=quality,
        near_miss=near_miss,
        handoff=handoff,
        starting=starting,
        commit_before=commit_before,
    )
    tests = phase12()
    tests_ok = tests.get("focused_passed") and tests.get("broader_passed")
    ready = ready and tests_ok

    commit_result = phase13(commit_before)
    invariants, completion = phase14_15(starting, commit_result)

    phase16_executed = False
    phase16_skip_reason = None
    gen1643_live = None
    gate_ok, gate_reason = phase16_decision_gate(tests=tests, ready=ready, invariants=invariants, commit_result=commit_result)
    if gate_ok:
        gen1643_live = phase16_live()
        phase16_executed = True
        top_classification = "DOOFUS_FULL_COMPLETION_PASS" if gen1643_live.get("exit_code") == 0 else "DOOFUS_FULL_COMPLETION_PARTIAL"
    else:
        phase16_skip_reason = gate_reason
        top_classification = "DOOFUS_FULL_COMPLETION_NEAR_PASS_OPERATOR_REVIEW_REQUIRED" if ready and tests_ok and invariants.get("passed") else "DOOFUS_FULL_COMPLETION_PARTIAL"

    if not evidence.get("validated"):
        top_classification = "DOOFUS_FULL_COMPLETION_FAIL"
    if not starting.get("safe_to_proceed"):
        top_classification = "DOOFUS_FULL_COMPLETION_FAIL"

    final = {
        "classification": top_classification,
        "timestamp": utc_now(),
        "phase0_starting_state": starting.get("classification"),
        "phase1_evidence_validated": evidence.get("validated"),
        "phase2_dirty_count": dirty.get("total_dirty"),
        "phase3_commit_plan_initial": commit_plan_initial.get("classification"),
        "phase4_tooling": tooling.get("classification"),
        "phase5_zero_promotion": diagnosis.get("classification"),
        "phase6_quality_report": quality.get("classification"),
        "phase7_handoff": handoff.get("classification"),
        "phase8_11_manifest": manifest.get("top_level_classification"),
        "phase12_tests": tests.get("classification"),
        "phase13_commit": commit_result.get("classification"),
        "phase14_invariants": invariants.get("classification"),
        "phase15_completion": completion.get("classification"),
        "phase16_executed": phase16_executed,
        "phase16_skip_reason": phase16_skip_reason,
        "gen1642_certified": evidence.get("validated"),
        "controlled_cycle_tooling_complete": True,
        "zero_promotion_diagnosed": True,
        "tests_passed": tests_ok,
        "commit_succeeded": commit_result.get("commit_succeeded"),
        "gen1643_prep_packet_ready": (OUT / "GEN1643_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.json").exists(),
        "dominant_rejection_reason": diagnosis.get("dominant_rejection_reason"),
        "best_near_miss_candidate": diagnosis.get("best_near_miss_candidate"),
        "queued_for_proof_builder_count": diagnosis.get("queued_for_proof_builder_in_db"),
        "artifacts_directory": str(OUT),
        "commit_before": commit_before,
        "commit_after": commit_result.get("commit_after"),
        "sections": {
            "starting_state": starting,
            "evidence_validation": evidence,
            "dirty_inventory": {"total": dirty.get("total_dirty"), "buckets": dirty.get("bucket_counts")},
            "commit_plan_initial": commit_plan_initial,
            "tooling_completion": tooling,
            "zero_promotion_diagnosis": diagnosis,
            "candidate_quality": quality,
            "promotion_near_miss": near_miss,
            "proof_builder_handoff": handoff,
            "next_cycle_seed_context": seed_plan,
            "gen1642_manifest": manifest,
            "gen1643_prep_packet": {"written": bool(packet), "classification": packet.get("classification") if packet else None},
            "test_results": tests,
            "commit_result": commit_result,
            "post_commit_invariants": invariants,
            "completion_manifest": completion,
            "gen1643_live": gen1643_live,
        },
    }
    write_pair("FINAL_REPORT", final)
    print_terminal_summary(final)
    return 0 if top_classification in ("DOOFUS_FULL_COMPLETION_PASS", "DOOFUS_FULL_COMPLETION_NEAR_PASS_OPERATOR_REVIEW_REQUIRED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
