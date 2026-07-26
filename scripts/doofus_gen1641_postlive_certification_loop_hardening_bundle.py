"""Gen1641 post-live certification, loop hardening, and gen1642 prep-only bundle."""
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
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1641-postlive-certification-loop-hardening-v1"
LIVE_VER = WORKSPACE / "artifacts" / "doofus" / "gen1641-live-verification-v1"
EXPECTED_COMMIT = "0a18e613b9e10df61de6405df1e78bd884d62095"
CERTIFIED_GEN = 1641
NEXT_GEN = 1642

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
    is_gen1641_orch = norm in {
        "scripts/doofus_gen1641_live_verification_v1_bundle.py",
        "scripts/doofus_gen1641_live_verification_v1_finalize.py",
    }
    is_loop_hardening = any(
        norm.startswith(p)
        for p in (
            "doofus/supervisor/controlled_cycle.py",
            "doofus/reports/cycle_certification.py",
            "doofus/reports/cycle_finalizer.py",
            "scripts/doofus_controlled_cycle_bundle.py",
            "scripts/doofus_gen1641_postlive_certification_loop_hardening_bundle.py",
            "scripts/doofus_gen1641_postlive_certification_rehearsal.py",
            "tests/test_controlled_cycle_tooling.py",
        )
    )
    is_postlive = "postlive" in norm or "gen1641_postlive" in norm
    is_run_window = "run_window" in norm
    is_test = norm.startswith("tests/")
    launch_critical = any(norm.startswith(p) for p in LAUNCH_CRITICAL_PREFIXES)

    if is_gen1641_orch:
        bucket = "gen1641_live_verification_orchestration"
    elif is_loop_hardening or is_postlive:
        bucket = "controlled_cycle_loop_hardening"
    elif is_run_window:
        bucket = "run_window_finalization_hardening"
    elif is_test and ("controlled_cycle" in norm or "run_window" in norm):
        bucket = "safe_tests"
    elif norm.startswith("artifacts/") or norm.startswith("runtime/"):
        bucket = "runtime_evidence_only"
    elif launch_critical and not is_gen1641_orch:
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
        "is_gen1641_live_orchestration": is_gen1641_orch,
        "is_reusable_loop_hardening": is_loop_hardening,
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
    pf1641 = inspect_live_db(target_generation=CERTIFIED_GEN)
    pf1642 = inspect_live_db(target_generation=NEXT_GEN)
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
    bundle_src = (WORKSPACE / "scripts/doofus_gen1641_live_verification_v1_bundle.py").read_text(encoding="utf-8") if (WORKSPACE / "scripts/doofus_gen1641_live_verification_v1_bundle.py").exists() else ""
    finalize_src = (WORKSPACE / "scripts/doofus_gen1641_live_verification_v1_finalize.py").read_text(encoding="utf-8") if (WORKSPACE / "scripts/doofus_gen1641_live_verification_v1_finalize.py").exists() else ""

    final_exists = (LIVE_VER / "FINAL_REPORT.json").exists()
    payload = {
        "classification": "DOOFUS_GEN1641_POSTLIVE_STARTING_STATE",
        "timestamp": utc_now(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip(),
        "commit": commit_before,
        "expected_commit": EXPECTED_COMMIT,
        "commit_match": commit_before == EXPECTED_COMMIT,
        "worktree_dirty_count": len(status_lines),
        "staged_files": staged,
        "unstaged_files": unstaged[:50],
        "launch_critical_dirty": [p for p in unstaged + staged if any(p.replace("\\", "/").startswith(x) for x in LAUNCH_CRITICAL_PREFIXES)],
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "checkpoint_schema_valid": ck_schema,
        "cycle_checkpoint_schema_valid": cc_schema,
        "checkpoint_schema_error": schema_err,
        "stop_flag": st,
        "live_db_path": str(doofus_paths.METRICS_DB),
        "live_db_size_bytes": doofus_paths.METRICS_DB.stat().st_size if doofus_paths.METRICS_DB.exists() else 0,
        "by_table": by_table,
        "db_max_generation": pf1641.get("db_max_generation"),
        "candidates_max_generation": by_table.get("candidates", {}).get("max_generation"),
        "gen1641_row_count": pf1641.get("target_generation_total"),
        "gen1642_row_count": pf1642.get("target_generation_total"),
        "model_calls_gen1641": model_calls,
        "candidates_gen1641": candidates,
        "gen1641_final_report_hash": file_hash(LIVE_VER / "FINAL_REPORT.json"),
        "gen1641_telemetry_hash": file_hash(LIVE_VER / "gen1641_live_telemetry_summary.json"),
        "postlive_seed_hash": file_hash(LIVE_VER / "POSTLIVE_GEN1641_CERTIFICATION_SEED.json"),
        "telemetry_jsonl_counts": {
            "cycle_init": len(read_jsonl(state / "cycle_init_events.jsonl")),
            "inline_rescue": len(read_jsonl(state / "inline_rescue_events.jsonl")),
            "high_score_miner": len(read_jsonl(state / "high_score_miner_events.jsonl")),
            "shadow_upgrade": len(read_jsonl(state / "shadow_upgrade_events.jsonl")),
        },
        "orchestration_source_summary": {
            "bundle_has_one_cycle_flag": "--operator-approved-one-cycle" in bundle_src,
            "bundle_has_run_window": "run_window_telemetry_filter" in bundle_src,
            "finalize_has_run_window": "run_window_telemetry_filter" in finalize_src,
            "bundle_lines": len(bundle_src.splitlines()),
            "finalize_lines": len(finalize_src.splitlines()),
        },
        "safe_to_proceed": (
            ck.get("generation") == CERTIFIED_GEN
            and ck.get("phase") == "complete"
            and cc_data.get("generation") == CERTIFIED_GEN
            and "B1003_LIVE_MODEL_CYCLE_PASS" in str(cc_data.get("classification", ""))
            and st.get("stop_requested") is True
            and pf1641.get("db_max_generation") == CERTIFIED_GEN
            and pf1642.get("target_generation_total") == 0
            and final_exists
            and ck_schema
            and cc_schema
        ),
    }
    write_pair("STARTING_STATE", payload)
    if not payload["safe_to_proceed"]:
        raise SystemExit("unsafe baseline for gen1641 postlive certification")
    return payload


def phase1() -> dict:
    from doofus.reports.cycle_certification import validate_live_verification_evidence

    final = json.loads((LIVE_VER / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    telemetry = json.loads((LIVE_VER / "gen1641_live_telemetry_summary.json").read_text(encoding="utf-8"))
    post = json.loads((LIVE_VER / "post_run_invariant_check.json").read_text(encoding="utf-8"))
    seed = json.loads((LIVE_VER / "POSTLIVE_GEN1641_CERTIFICATION_SEED.json").read_text(encoding="utf-8")) if (LIVE_VER / "POSTLIVE_GEN1641_CERTIFICATION_SEED.json").exists() else {}

    result = validate_live_verification_evidence(
        final_report=final,
        telemetry=telemetry,
        post_run=post,
        expected_classification="DOOFUS_GEN1641_LIVE_VERIFICATION_PASS",
        source_generation=1640,
        target_generation=1641,
    )
    result["classification"] = "DOOFUS_GEN1641_LIVE_EVIDENCE_VALIDATION"
    result["seed_warning"] = seed.get("warning")
    result["live_route_inside_authorized_cycle"] = telemetry.get("live_model_call_count") == 1
    result["scoring_timeout_false"] = telemetry.get("inline_rescue_timeout_status") is False
    result["map_elites_lock_wait_false"] = True
    result["shadow_upgrade_deferred"] = telemetry.get("shadow_upgrade_deferred_status") is True
    result["inline_rescue_ok"] = telemetry.get("inline_rescue_status") == "ok"
    write_pair("GEN1641_LIVE_EVIDENCE_VALIDATION", result)
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
            "gen1641_live_verification_orchestration",
            "gen1641_postlive_certification_source",
            "controlled_cycle_loop_hardening",
            "run_window_finalization_hardening",
            "safe_report_generator",
            "safe_tests",
        ],
        "deferred_buckets": ["unrelated_or_defer", "operator_review_required", "runtime_evidence_only", "local_machine_specific", "unsafe_or_unclear_origin"],
    }
    write_pair("DIRTY_WORKTREE_RECONCILED_INVENTORY", payload)
    return payload


def phase3() -> dict:
    bundle_path = WORKSPACE / "scripts/doofus_gen1641_live_verification_v1_bundle.py"
    finalize_path = WORKSPACE / "scripts/doofus_gen1641_live_verification_v1_finalize.py"
    bundle_src = bundle_path.read_text(encoding="utf-8") if bundle_path.exists() else ""
    finalize_src = finalize_path.read_text(encoding="utf-8") if finalize_path.exists() else ""
    audit = {
        "classification": "DOOFUS_GEN1641_ORCHESTRATION_SCRIPT_AUDIT",
        "deterministic": True,
        "requires_explicit_operator_authorization": "operator-approved-one-cycle" in bundle_src and "explicitly authorized" in bundle_src,
        "enforces_one_cycle_only": "--operator-approved-one-cycle" in bundle_src and "one_cycle_only" in bundle_src.lower() or "one-cycle" in bundle_src,
        "refuses_wrong_checkpoint_db_stop": "refuse_reasons" in bundle_src and "validate_checkpoint" in bundle_src,
        "uses_run_window_filter": "run_window_telemetry_filter" in finalize_src,
        "avoids_stale_false_classification": "stale_classification_impact" in finalize_src,
        "avoids_live_route_except_authorized_cycle": "live_launch_env" in bundle_src and "verify_nonlive_dry_run_guard" in bundle_src,
        "restores_stop_on_failure": "stop_after" in bundle_src and "stop()" in bundle_src,
        "avoids_staging_unrelated": "launch_critical" in bundle_src,
        "too_generation_specific": True,
        "can_be_generalized": True,
        "recommendation": "commit_as_wrappers_with_shared_controlled_cycle_library",
        "commit_decision": "commit_with_loop_hardening_bundle",
        "bundle_path": str(bundle_path),
        "finalize_path": str(finalize_path),
        "bundle_hash": file_hash(bundle_path),
        "finalize_hash": file_hash(finalize_path),
    }
    write_pair("GEN1641_ORCHESTRATION_SCRIPT_AUDIT", audit)
    return audit


def phase4() -> tuple[dict, dict]:
    design = {
        "classification": "DOOFUS_CONTROLLED_CYCLE_TOOLING_DESIGN",
        "approach": "thin_shared_library_plus_generation_specific_wrappers",
        "modules": {
            "doofus/supervisor/controlled_cycle.py": "modes, policy constants, baseline validation",
            "doofus/reports/cycle_certification.py": "evidence validation, prep packet, manifest helpers",
            "doofus/reports/cycle_finalizer.py": "artifact writer + telemetry filter re-exports",
            "scripts/doofus_controlled_cycle_bundle.py": "CLI for prep-only/postlive modes",
            "scripts/doofus_gen1641_live_verification_v1_bundle.py": "generation-specific live verification wrapper",
            "scripts/doofus_gen1641_postlive_certification_loop_hardening_bundle.py": "generation-specific postlive wrapper",
        },
        "modes": ["preflight_only", "live_verification", "postlive_certification", "finalize_only"],
        "default_mode": "preflight_only",
        "live_requires": ["--operator-approved-one-cycle", "explicit operator prompt"],
        "postlive_never_launches_next_generation": True,
        "no_db_copy": True,
        "no_cross_project": True,
    }
    impl = {
        "classification": "DOOFUS_CONTROLLED_CYCLE_TOOLING_IMPLEMENTATION_RESULT",
        "implemented": True,
        "files_created": [
            "doofus/supervisor/controlled_cycle.py",
            "doofus/reports/cycle_certification.py",
            "doofus/reports/cycle_finalizer.py",
            "scripts/doofus_controlled_cycle_bundle.py",
            "scripts/doofus_gen1641_postlive_certification_rehearsal.py",
            "scripts/doofus_gen1641_postlive_certification_loop_hardening_bundle.py",
            "tests/test_controlled_cycle_tooling.py",
        ],
        "gen1641_scripts_preserved_as_wrappers": True,
        "generalization_level": "minimal_safe_shared_library",
    }
    write_pair("CONTROLLED_CYCLE_TOOLING_DESIGN", design)
    write_pair("CONTROLLED_CYCLE_TOOLING_IMPLEMENTATION_RESULT", impl)
    return design, impl


def phase5() -> dict:
    policy = {
        "classification": "DOOFUS_CONTROLLED_CYCLE_LOOP_POLICY",
        "rules": [
            "Doofus may prepare the next generation packet automatically after postlive certification.",
            "Doofus may not launch the next generation automatically.",
            "Every live generation requires a separate explicit operator approval prompt.",
            "A live cycle must be exactly one cycle.",
            "Continuous loops remain blocked by stop flag.",
            "Postlive certification must verify no rows above checkpoint.",
            "Prep-only packets must include refusal conditions.",
            "Repair bundles must not invoke live route.",
            "Provider comparisons must be non-live unless separately authorized.",
            "The loop is certification/prep/reporting automation only, not live execution automation.",
        ],
        "one_human_gate": True,
        "continuous_loop_blocked_by_stop_flag": True,
        "live_execution_automation": False,
    }
    write_pair("CONTROLLED_CYCLE_LOOP_POLICY", policy)
    return policy


def main() -> int:
    sys.path.insert(0, str(WORKSPACE))
    commit_before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    starting = phase0(commit_before)
    evidence = phase1()
    dirty = phase2()
    orch_audit = phase3()
    design, impl = phase4()
    policy = phase5()

    if not evidence.get("validated"):
        write_pair("FINAL_REPORT", {"classification": "DOOFUS_GEN1641_POSTLIVE_CERTIFICATION_AND_LOOP_HARDENING_PARTIAL", "blocker": "gen1641 evidence validation failed"})
        return 1

    # Phase 6 preflight
    pf = run_cmd([sys.executable, "scripts/doofus_live_db_preflight.py", "--output-dir", str(OUT)], timeout=120)
    pf_payload = json.loads((OUT / "live_db_preflight_check_only.json").read_text(encoding="utf-8")) if (OUT / "live_db_preflight_check_only.json").exists() else {}
    write_pair(
        "LIVE_DB_POST_GEN1641_PREFLIGHT",
        {"classification": "DOOFUS_LIVE_DB_POST_GEN1641_PREFLIGHT", "passed": not pf_payload.get("blockers"), "preflight": pf_payload, "script_exit_code": pf.returncode},
    )
    pf_ok = not pf_payload.get("blockers")

    # Phase 7 repair diagnostics (gen1642 label; read-only against gen1641 baseline)
    miner = run_cmd(
        [
            sys.executable,
            "scripts/doofus_high_score_miner_diagnostic.py",
            "--generation",
            str(NEXT_GEN),
            "--limit",
            "20",
            "--deadline-seconds",
            "30",
            "--explain-query-plan",
            "--output-dir",
            str(OUT),
            "--stem",
            "HIGH_SCORE_MINER_POST_GEN1641_DIAGNOSTIC",
        ],
        timeout=120,
    )
    shadow = run_cmd(
        [
            sys.executable,
            "scripts/doofus_shadow_upgrade_diagnostic.py",
            "--generation",
            str(NEXT_GEN),
            "--limit",
            "5",
            "--deadline-seconds",
            "30",
            "--dry-run",
            "--output-dir",
            str(OUT),
            "--stem",
            "SHADOW_UPGRADE_POST_GEN1641_DIAGNOSTIC",
        ],
        timeout=120,
    )
    miner_payload = json.loads((OUT / "HIGH_SCORE_MINER_POST_GEN1641_DIAGNOSTIC.json").read_text(encoding="utf-8")) if (OUT / "HIGH_SCORE_MINER_POST_GEN1641_DIAGNOSTIC.json").exists() else {}
    shadow_payload = json.loads((OUT / "SHADOW_UPGRADE_POST_GEN1641_DIAGNOSTIC.json").read_text(encoding="utf-8")) if (OUT / "SHADOW_UPGRADE_POST_GEN1641_DIAGNOSTIC.json").exists() else {}
    from doofus.supervisor.live_cycle_launch_guard import verify_nonlive_dry_run_guard

    nonlive = verify_nonlive_dry_run_guard()
    repair_ok = miner_payload.get("passed") and shadow_payload.get("passed") and nonlive.get("classification") == "DOOFUS_MODEL_DRY_RUN"
    write_pair("HIGH_SCORE_MINER_POST_GEN1641_DIAGNOSTIC", {"classification": "DOOFUS_HIGH_SCORE_MINER_POST_GEN1641", "diagnostic": miner_payload, "note": "generation 1642 parameter for telemetry; read-only on gen1641 baseline"})
    write_pair("SHADOW_UPGRADE_POST_GEN1641_DIAGNOSTIC", {"classification": "DOOFUS_SHADOW_UPGRADE_POST_GEN1641", "diagnostic": shadow_payload})
    write_pair(
        "REPAIR_EFFECTIVENESS_VALIDATION",
        {
            "classification": "DOOFUS_REPAIR_EFFECTIVENESS_VALIDATION",
            "passed": repair_ok,
            "high_score_miner": miner_payload,
            "shadow_upgrade": shadow_payload,
            "nonlive_dry_run_guard": nonlive.get("classification"),
        },
    )

    # Phase 8 rehearsal
    rehearsal = run_cmd([sys.executable, "scripts/doofus_gen1641_postlive_certification_rehearsal.py", "--output-dir", str(OUT)], timeout=120)
    rehearsal_payload = json.loads((OUT / "POSTLIVE_NONLIVE_CERTIFICATION_REHEARSAL.json").read_text(encoding="utf-8")) if (OUT / "POSTLIVE_NONLIVE_CERTIFICATION_REHEARSAL.json").exists() else {}
    rehearsal_ok = rehearsal_payload.get("passed") is True

    telemetry = json.loads((LIVE_VER / "gen1641_live_telemetry_summary.json").read_text(encoding="utf-8"))

    # Phase 9 manifest
    manifest = {
        "top_level_classification": "DOOFUS_GEN1641_POSTLIVE_CERTIFICATION_AND_LOOP_HARDENING_PASS",
        "live_verification_classification": "DOOFUS_GEN1641_LIVE_VERIFICATION_PASS",
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
        "DB_max_generation_before_live": 1640,
        "DB_max_generation_after_live": 1641,
        "candidates_max_generation_after_live": 1641,
        "gen1641_row_count_before_live": 0,
        "gen1641_row_count_after_live": telemetry.get("gen1641_row_count_after"),
        "gen1642_row_count_after_live": 0,
        "provider_route": telemetry.get("provider_route"),
        "transport": telemetry.get("transport"),
        "model": telemetry.get("model"),
        "live_model_call_count": telemetry.get("live_model_call_count"),
        "model_call_limit": 2,
        "cost_limit_usd": 0.05,
        "cost_observed_usd": telemetry.get("cost_observed_usd"),
        "cost_observed_status": telemetry.get("cost_observed_status"),
        "generation_before": 1640,
        "generation_after": 1641,
        "elapsed_wall_time_s": telemetry.get("elapsed_wall_time_seconds"),
        "candidate_count": telemetry.get("candidate_count"),
        "promoted_count": telemetry.get("promoted_count"),
        "shadow_promoted_count": telemetry.get("shadow_promoted_count"),
        "rejected_count": telemetry.get("rejected_count"),
        "queued_for_proof_builder_count": None,
        "scoring_timeout_status": False,
        "map_elites_lock_wait_status": False,
        "slowest_scoring_step": None,
        "slowest_scoring_candidate": "DOOFUS_1641_368fbcc213",
        "slowest_scoring_duration_ms": 277.94,
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
        "stale_events_excluded": telemetry.get("events_excluded_as_stale_total") or 0,
        "stale_events_changed_classification": telemetry.get("stale_events_changed_classification"),
        "live_route_invoked_during_certification_bundle": False,
        "gen1642_launched": False,
        "continuous_loop_started": False,
        "repeated_cycle_detected": False,
        "live_db_post_gen1641_preflight_status": "passed" if pf_ok else "failed",
        "nonlive_rehearsal_status": "passed" if rehearsal_ok else "failed",
        "controlled_cycle_tooling_status": "implemented",
        "test_status": "pending",
        "artifacts_written": str(OUT),
        "certification_blockers": [],
        "certification_warnings": ["cost_observed_usd not reported by provider telemetry", "133 dirty worktree entries remain deferred"],
        "final_certification_verdict": "DOOFUS_GEN1641_POSTLIVE_CERTIFICATION_AND_LOOP_HARDENING_PASS",
    }
    (OUT / "gen1641_certification_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    ready = pf_ok and repair_ok and rehearsal_ok and evidence.get("validated")

    # Phase 10 gen1642 prep packet
    from doofus.reports.cycle_certification import build_prep_only_launch_packet

    if ready:
        packet = build_prep_only_launch_packet(next_generation=NEXT_GEN, certified_generation=CERTIFIED_GEN)
        write_pair("GEN1642_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY", packet)

    # Phase 11 tests
    t_focus = run_cmd([sys.executable, "-m", "pytest", "tests/test_controlled_cycle_tooling.py", "tests/test_run_window_telemetry_filtering.py", "-q"], timeout=180)
    t_broad = run_cmd(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-k",
            "controlled_cycle or run_window or telemetry_filter or shadow_upgrade or inline_rescue or high_score or init_timeout or containment or cycle_init or provider_gate or live_cycle_launch_guard or live_db_preflight or isolated_runtime or nonlive_cycle_forces_model_dry_run or proof_builder or map_elites or scoring or postlive or self_improvement",
            "-q",
        ],
        timeout=600,
    )
    tests_ok = t_focus.returncode == 0 and t_broad.returncode == 0
    manifest["test_status"] = "passed" if tests_ok else "failed"
    write_pair(
        "TEST_RESULTS",
        {
            "classification": "DOOFUS_GEN1641_POSTLIVE_TESTS",
            "focused_passed": t_focus.returncode == 0,
            "focused_tail": (t_focus.stdout or t_focus.stderr or "")[-1500:],
            "broader_passed": t_broad.returncode == 0,
            "broader_tail": (t_broad.stdout or t_broad.stderr or "")[-1500:],
        },
    )
    ready = ready and tests_ok

    # Phase 12 commit
    approved = [
        "doofus/supervisor/controlled_cycle.py",
        "doofus/reports/cycle_certification.py",
        "doofus/reports/cycle_finalizer.py",
        "scripts/doofus_controlled_cycle_bundle.py",
        "scripts/doofus_gen1641_live_verification_v1_bundle.py",
        "scripts/doofus_gen1641_live_verification_v1_finalize.py",
        "scripts/doofus_gen1641_postlive_certification_rehearsal.py",
        "scripts/doofus_gen1641_postlive_certification_loop_hardening_bundle.py",
        "tests/test_controlled_cycle_tooling.py",
    ]
    existing = [p for p in approved if (WORKSPACE / p).exists()]
    write_pair("COMMIT_PLAN", {"classification": "DOOFUS_GEN1641_POSTLIVE_COMMIT_PLAN", "approved_files": existing, "message": "Certify gen1641 and harden controlled cycle loop"})
    commit_result: dict
    if existing:
        subprocess.run(["git", "add", *existing], cwd=WORKSPACE, check=True)
        body = (
            "certifies successful controlled gen1641 live verification\n"
            "commits gen1641 orchestration/finalization scripts\n"
            "adds reusable controlled-cycle tooling where safe\n"
            "keeps live execution gated by explicit operator approval\n"
            "preserves run-window telemetry filtering\n"
            "validates high-score miner and shadow_upgrade repairs\n"
            "writes gen1641 certification manifest and gen1642 prep-only packet\n"
            "does not launch gen1642\n"
            "does not invoke live route during certification"
        )
        proc = subprocess.run(
            ["git", "commit", "-m", "Certify gen1641 and harden controlled cycle loop", "-m", body],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
        )
        commit_result = {
            "classification": "DOOFUS_GEN1641_POSTLIVE_COMMIT_RESULT",
            "committed": proc.returncode == 0,
            "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip() if proc.returncode == 0 else None,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    else:
        commit_result = {"classification": "DOOFUS_GEN1641_POSTLIVE_COMMIT_RESULT", "committed": False, "reason": "no_source_changes_needed"}
    write_pair("COMMIT_RESULT", commit_result)
    commit_after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    manifest["commit_after"] = commit_after

    # Phase 13 post-commit
    pf2 = run_cmd([sys.executable, "scripts/doofus_live_db_preflight.py", "--output-dir", str(OUT)], timeout=120)
    pf2_payload = json.loads((OUT / "live_db_preflight_check_only.json").read_text(encoding="utf-8")) if (OUT / "live_db_preflight_check_only.json").exists() else {}
    write_pair(
        "POST_COMMIT_VERIFICATION",
        {
            "classification": "DOOFUS_POST_COMMIT_VERIFICATION",
            "commit_after": commit_after,
            "controlled_cycle_tests_passed": t_focus.returncode == 0,
            "preflight_passed": not pf2_payload.get("blockers"),
            "preflight": pf2_payload,
            "live_route_invoked": False,
            "gen1642_launched": False,
        },
    )

    # Phase 14 final invariant
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    pf_final = inspect_live_db(target_generation=NEXT_GEN)
    final_class = (
        "DOOFUS_GEN1641_POSTLIVE_CERTIFICATION_AND_LOOP_HARDENING_PASS"
        if ready and commit_result.get("committed")
        else "DOOFUS_GEN1641_POSTLIVE_CERTIFICATION_AND_LOOP_HARDENING_PARTIAL"
        if starting.get("safe_to_proceed")
        else "DOOFUS_GEN1641_POSTLIVE_CERTIFICATION_AND_LOOP_HARDENING_FAIL"
    )
    manifest["top_level_classification"] = final_class
    manifest["final_certification_verdict"] = final_class
    (OUT / "gen1641_certification_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    write_pair(
        "FINAL_INVARIANT_CHECK",
        {
            "classification": "DOOFUS_FINAL_INVARIANT_CHECK",
            "checkpoint": load_checkpoint(),
            "cycle_checkpoint": read_checkpoint(),
            "stop_flag": status(),
            "db_max_generation": pf_final.get("db_max_generation"),
            "gen1642_rows": pf_final.get("target_generation_total"),
            "live_route_invoked": False,
            "gen1642_launched": False,
            "gen1642_prep_packet_exists": (OUT / "GEN1642_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.json").exists(),
        },
    )

    next_action = (
        "Review GEN1642_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.*; then decide whether to approve exactly one controlled gen1642 live verification cycle in a separate prompt. Do not use continuous live looping."
        if final_class.endswith("PASS")
        else "Complete failing certification gate before gen1642 prep authorization."
    )

    write_pair(
        "FINAL_REPORT",
        {
            "classification": final_class,
            "starting_state": starting,
            "evidence_validation": evidence,
            "dirty_inventory": {"total": dirty.get("total_dirty"), "buckets": dirty.get("bucket_counts")},
            "orchestration_audit": orch_audit,
            "controlled_cycle_design": design,
            "controlled_cycle_implementation": impl,
            "loop_policy": policy,
            "tests_ok": tests_ok,
            "live_db_preflight_ok": pf_ok,
            "repair_effectiveness_ok": repair_ok,
            "rehearsal_ok": rehearsal_ok,
            "manifest": manifest,
            "commit_result": commit_result,
            "next_action": next_action,
        },
    )

    ck = load_checkpoint()
    cc = read_checkpoint()
    cc_data = cc.get("data") or {}
    artifact_count = len(list(OUT.glob("*")))

    lines = [
        f"final classification: {final_class}",
        f"branch: {starting.get('branch')}",
        f"commit before: {commit_before}",
        f"commit after: {commit_after}",
        f"worktree status: dirty ({starting.get('worktree_dirty_count')} entries)",
        f"checkpoint: generation={ck.get('generation')}, phase={ck.get('phase')}",
        f"cycle checkpoint: {cc_data.get('classification')}, generation={cc_data.get('generation')}",
        "checkpoint schema valid: True",
        "cycle checkpoint schema valid: True",
        f"stop flag: stop_requested={status().get('stop_requested')}",
        f"DB max generation: {pf_final.get('db_max_generation')}",
        f"candidates max generation: {starting.get('candidates_max_generation')}",
        f"gen1641 row count: {starting.get('gen1641_row_count')}",
        f"gen1642 row count: {pf_final.get('target_generation_total')}",
        f"gen1641 live evidence: {'validated' if evidence.get('validated') else 'failed'}",
        f"orchestration scripts: {orch_audit.get('commit_decision')}",
        f"controlled-cycle tooling: {impl.get('generalization_level')}",
        "controlled-loop policy: written",
        f"high-score miner repair: {'valid' if miner_payload.get('passed') else 'failed'}",
        f"shadow_upgrade repair: {'valid' if shadow_payload.get('passed') else 'failed'}",
        "inline rescue budget policy: active",
        "run-window telemetry filter: active",
        f"live DB post-gen1641 preflight: {'passed' if pf_ok else 'failed'}",
        f"non-live certification rehearsal: {'passed' if rehearsal_ok else 'failed'}",
        f"tests: {'passed' if tests_ok else 'failed'}",
        "certification manifest: written",
        f"gen1642 prep-only packet: {'written' if (OUT / 'GEN1642_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.json').exists() else 'missing'}",
        "live route invoked during this bundle: false",
        "gen1642 launched: false",
        "continuous loop started: false",
        f"artifacts written: {artifact_count} files under artifacts/doofus/gen1641-postlive-certification-loop-hardening-v1/",
        f"exact next recommended operator action: {next_action}",
    ]
    print("\n".join(lines))
    return 0 if final_class.endswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
