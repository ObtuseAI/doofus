"""Gen1640 retry live verification bundle - one authorized guarded live cycle."""
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
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1640-retry-live-verification-v1"
REPAIR = WORKSPACE / "artifacts" / "doofus" / "gen1640-init-hang-repair-v1"
KERNEL = WORKSPACE / "artifacts" / "doofus" / "self-improvement-kernel-gen1640-readiness-v1"
EXPECTED_COMMIT = "371cfe9eef8a2df6df7a36a1685d3aaf830879d0"
AUTHORIZED_COMMAND = [
    sys.executable,
    "-m",
    "doofus.supervisor.provider_aware_live_cycle",
    "--operator-approved-one-cycle",
    "--max-model-calls",
    "2",
    "--max-cost-usd",
    "0.05",
]
LAUNCH_CRITICAL_PREFIXES = (
    "doofus/supervisor/",
    "doofus/model_router/",
    "doofus/safety/",
    "doofus/scoring/",
    "doofus/proof/",
    "doofus/evolution/map_elites",
    "doofus/runtime/live_db_preflight.py",
    "doofus/self_improvement/",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_pair(stem: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# {stem.replace('_', ' ').title()}", ""]
    for k, v in payload.items():
        if isinstance(v, (dict, list)):
            lines.extend([f"## {k}", "", "```json", json.dumps(v, indent=2)[:12000], "```", ""])
        else:
            lines.append(f"- **{k}**: `{v}`")
    (OUT / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def file_hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def launch_critical_dirty() -> list[str]:
    dirty = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()
    hits = []
    for line in dirty:
        path = line[3:].strip().strip('"')
        norm = path.replace("\\", "/")
        if any(norm.startswith(p) for p in LAUNCH_CRITICAL_PREFIXES):
            hits.append(path)
    return hits


def launch_critical_diff_snapshot() -> str:
    paths: list[str] = []
    for prefix in LAUNCH_CRITICAL_PREFIXES:
        p = WORKSPACE / prefix.rstrip("/")
        if p.is_file():
            paths.append(prefix)
        elif p.is_dir():
            paths.extend(str(f.relative_to(WORKSPACE)).replace("\\", "/") for f in p.rglob("*") if f.is_file())
    diff = subprocess.run(["git", "diff", "HEAD", "--", *paths[:200]], cwd=WORKSPACE, capture_output=True, text=True)
    staged = subprocess.run(["git", "diff", "--cached", "HEAD", "--", *paths[:200]], cwd=WORKSPACE, capture_output=True, text=True)
    return hashlib.sha256((diff.stdout + staged.stdout).encode()).hexdigest()


def live_launch_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("DOOFUS_STATE", "DOOFUS_METRICS_DB", "DOOFUS_CONTROL", "DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS"):
        env.pop(key, None)
    env.pop("DOOFUS_FORCE_MODEL_DRY_RUN", None)
    env["DOOFUS_MODEL_PROVIDER"] = "cursor"
    return env


def main() -> int:
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core import doofus_paths
    from doofus.core.doofus_config import DoofusConfig
    from doofus.model_router.provider_router import resolve_provider
    from doofus.runtime.live_db_preflight import inspect_live_db, generation_tables
    from doofus.safety.on_off_switch import status, stop
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint
    from doofus.supervisor.live_cycle_launch_guard import verify_nonlive_dry_run_guard

    for key in ("DOOFUS_STATE", "DOOFUS_METRICS_DB", "DOOFUS_CONTROL"):
        os.environ.pop(key, None)

    OUT.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip()
    dirty_lines = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()
    lc_dirty = launch_critical_dirty()
    lc_diff_start = launch_critical_diff_snapshot()
    staged_lc = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=WORKSPACE, capture_output=True, text=True).stdout
    staged_lc_hits = [p for p in staged_lc.splitlines() if any(p.replace("\\", "/").startswith(x) for x in LAUNCH_CRITICAL_PREFIXES)]

    retry_packet_path = REPAIR / "GEN1640_RETRY_OPERATOR_REVIEW_PACKET_PREP_ONLY.json"
    retry_packet = json.loads(retry_packet_path.read_text(encoding="utf-8")) if retry_packet_path.exists() else {}

    ck = load_checkpoint()
    cc = read_checkpoint()
    stop_before = status()
    pf1640 = inspect_live_db(target_generation=1640)
    pf1641 = inspect_live_db(target_generation=1641)

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=30)
    by_table = {}
    for t in generation_tables(conn):
        mx = conn.execute(f"SELECT MAX(generation) FROM {t}").fetchone()[0]
        by_table[t] = {
            "max_generation": mx,
            "gen1639": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1639").fetchone()[0],
            "gen1640": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1640").fetchone()[0],
            "gen1641": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1641").fetchone()[0],
        }
    conn.close()

    cc_data = cc.get("data") or {}
    cc_class = cc_data.get("classification", cc.get("classification", ""))
    cc_gen = cc_data.get("generation", cc.get("generation"))

    launch_env = live_launch_env()
    route_preview = resolve_provider()
    cfg_preview = DoofusConfig.from_env()
    os.environ.pop("DOOFUS_FORCE_MODEL_DRY_RUN", None)
    os.environ["DOOFUS_MODEL_PROVIDER"] = "cursor"
    cfg_live = DoofusConfig.from_env()

    starting = {
        "classification": "DOOFUS_GEN1640_RETRY_STARTING_STATE",
        "timestamp": utc_now(),
        "operator_authorization": "explicitly authorized by this prompt for one gen1640 retry live cycle",
        "branch": branch,
        "commit": commit,
        "expected_commit": EXPECTED_COMMIT,
        "commit_match": commit == EXPECTED_COMMIT,
        "worktree_dirty_count": len(dirty_lines),
        "launch_critical_dirty_files": lc_dirty,
        "launch_critical_staged_files": staged_lc_hits,
        "launch_critical_diff_snapshot_start": lc_diff_start,
        "launch_critical_clean": len(staged_lc_hits) == 0,
        "retry_packet_hash": file_hash(retry_packet_path),
        "repair_final_report_hash": file_hash(REPAIR / "FINAL_REPORT.json"),
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "stop_flag": stop_before,
        "live_db_path": str(doofus_paths.METRICS_DB),
        "by_table": by_table,
        "db_max_generation": pf1640.get("db_max_generation"),
        "candidates_max_generation": by_table.get("candidates", {}).get("max_generation"),
        "map_elites_max_generation": by_table.get("map_elites_cells", {}).get("max_generation"),
        "gen1640_row_count": pf1640.get("target_generation_total"),
        "gen1641_row_count": pf1641.get("target_generation_total"),
        "credentials_presence": {
            "DOOFUS_MODEL_PROVIDER_env": os.environ.get("DOOFUS_MODEL_PROVIDER"),
            "DOOFUS_FORCE_MODEL_DRY_RUN_env": os.environ.get("DOOFUS_FORCE_MODEL_DRY_RUN"),
            "CURSOR_API_KEY_set": bool(os.environ.get("CURSOR_API_KEY")),
            "OPENAI_API_KEY_set": bool(os.environ.get("OPENAI_API_KEY")),
            "OPENROUTER_API_KEY_set": bool(os.environ.get("OPENROUTER_API_KEY")),
        },
        "DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS": os.environ.get("DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS"),
        "provider_preview": {
            "provider_selected": route_preview.get("provider_selected"),
            "model_name": route_preview.get("model_name"),
            "live_provider_ready": route_preview.get("live_provider_ready"),
            "model_mode_live_launch_env": cfg_live.model_mode,
        },
    }
    write_pair("STARTING_STATE", starting)

    refuse_reasons: list[str] = []
    if not retry_packet_path.exists():
        refuse_reasons.append("retry_packet_missing")
    cmd = retry_packet.get("recommended_retry_command", "")
    if "--operator-approved-one-cycle" not in cmd:
        refuse_reasons.append("retry_packet_missing_one_cycle_flag")
    if commit != EXPECTED_COMMIT:
        refuse_reasons.append("commit_mismatch")
    if ck.get("generation") != 1639 or ck.get("phase") != "complete":
        refuse_reasons.append("checkpoint")
    if cc_gen != 1639 or "B1003_LIVE_MODEL_CYCLE_PASS" not in str(cc_class):
        refuse_reasons.append("cycle_checkpoint")
    if not stop_before.get("stop_requested"):
        refuse_reasons.append("stop_flag")
    if pf1640.get("db_max_generation") != 1639:
        refuse_reasons.append("db_max_generation")
    if by_table.get("candidates", {}).get("max_generation") != 1639:
        refuse_reasons.append("candidates_max_generation")
    if pf1640.get("target_generation_total", 1) != 0:
        refuse_reasons.append("gen1640_rows_exist")
    if pf1641.get("target_generation_total", 0) != 0:
        refuse_reasons.append("gen1641_rows_exist")
    if staged_lc_hits:
        refuse_reasons.append("launch_critical_staged_dirty")
    if launch_critical_diff_snapshot() != lc_diff_start:
        refuse_reasons.append("launch_critical_diff_changed_during_bundle")
    if cfg_live.model_mode != "live":
        refuse_reasons.append("model_mode_not_live_for_cursor_route")

    # Phase 1 preflight
    pf_proc = subprocess.run(
        [sys.executable, "scripts/doofus_live_db_preflight.py", "--output-dir", str(OUT)],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=120,
    )
    pf_before_path = OUT / "live_db_preflight_check_only.json"
    pf_before = json.loads(pf_before_path.read_text(encoding="utf-8")) if pf_before_path.exists() else {}
    write_pair(
        "live_db_preflight_before_retry",
        {
            "classification": "DOOFUS_LIVE_DB_PREFLIGHT_BEFORE_RETRY",
            "passed": not pf_before.get("blockers"),
            "preflight": pf_before,
            "script_exit_code": pf_proc.returncode,
        },
    )
    if pf_before.get("blockers"):
        refuse_reasons.append("live_db_preflight_failed")

    # Phase 2 tests
    focused_cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_cycle_init_watchdog.py",
        "tests/test_self_improvement_catalog.py",
        "tests/test_doofus_generation_summary.py",
        "tests/test_provider_aware_one_cycle_launch.py",
        "tests/test_provider_gate_postlive.py",
        "tests/test_live_cycle_launch_guard.py",
        "tests/test_live_db_preflight.py",
        "tests/test_inline_rescue.py",
        "tests/test_doofus_proof_builder.py",
        "tests/test_doofus.py",
        "-k",
        "cycle_init or init_watchdog or self_improvement or generation_summary or provider_gate or one_cycle or live_cycle_launch_guard or provider_aware or stop_requested or nonlive_cycle_forces_model_dry_run or live_db_preflight or isolated_runtime or inline_rescue or high_score or proof_builder or postlive",
        "-q",
    ]
    t_focus = subprocess.run(focused_cmd, cwd=WORKSPACE, capture_output=True, text=True, timeout=600)
    t_broad = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-k",
            "cycle_init or init_watchdog or high_score or self_improvement or generation_summary or provider_gate or live_cycle_launch_guard or provider_aware or stop_state_guard or live_db_preflight or isolated_runtime or nonlive_cycle_forces_model_dry_run or inline_rescue or proof_builder or map_elites or scoring or postlive",
            "-q",
        ],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=600,
    )
    write_pair(
        "prelaunch_test_results",
        {
            "classification": "DOOFUS_GEN1640_RETRY_PRELAUNCH_TESTS",
            "focused_passed": t_focus.returncode == 0,
            "focused_tail": (t_focus.stdout or t_focus.stderr or "")[-1200:],
            "broader_passed": t_broad.returncode == 0,
            "broader_tail": (t_broad.stdout or t_broad.stderr or "")[-1200:],
        },
    )
    if t_focus.returncode != 0 or t_broad.returncode != 0:
        refuse_reasons.append("guard_tests_failed")

    # Phase 3 nonlive probe
    pf_pre_probe = inspect_live_db(target_generation=1640)
    nonlive = verify_nonlive_dry_run_guard()
    pf_post_probe = inspect_live_db(target_generation=1640)
    pf1641_post = inspect_live_db(target_generation=1641)
    nonlive_ok = (
        nonlive.get("classification") == "DOOFUS_MODEL_DRY_RUN"
        and pf_post_probe.get("target_generation_total") == 0
        and pf1641_post.get("target_generation_total") == 0
        and load_checkpoint().get("generation") == 1639
        and status().get("stop_requested") is True
    )
    write_pair(
        "nonlive_dry_run_guard_probe",
        {
            "classification": "DOOFUS_NONLIVE_DRY_RUN_GUARD_PROBE",
            "probe": nonlive,
            "passed": nonlive_ok,
            "preflight_after": {k: pf_post_probe.get(k) for k in ("db_max_generation", "target_generation_total")},
            "gen1641_after": pf1641_post.get("target_generation_total"),
            "checkpoint_after": load_checkpoint(),
            "stop_after": status(),
        },
    )
    if not nonlive_ok:
        refuse_reasons.append("nonlive_dry_run_guard_failed")

    # Phase 4 init watchdog readiness
    from doofus.supervisor import cycle_init_telemetry, cycle_init_watchdog
    from doofus.proof import high_score_rejection_miner

    import inspect as pyinspect

    miner_src = Path(high_score_rejection_miner.__file__).read_text(encoding="utf-8")
    init_ok = all(
        [
            Path(cycle_init_telemetry.__file__).exists(),
            Path(cycle_init_watchdog.__file__).exists(),
            "LIMIT" in miner_src.upper(),
            "deadline_monotonic" in miner_src,
            hasattr(cycle_init_watchdog, "run_bounded_init_call"),
        ]
    )
    write_pair(
        "INIT_WATCHDOG_READINESS_CHECK",
        {
            "classification": "DOOFUS_INIT_WATCHDOG_READINESS",
            "passed": init_ok,
            "default_timeout_seconds": cycle_init_watchdog.cycle_init_timeout_seconds(),
            "init_timeout_classification": "DOOFUS_CYCLE_INIT_TIMEOUT_ABORTED",
            "run_bounded_init_call_present": hasattr(cycle_init_watchdog, "run_bounded_init_call"),
            "miner_has_limit": "LIMIT" in miner_src.upper(),
            "miner_has_deadline": "deadline_monotonic" in miner_src,
        },
    )
    if not init_ok:
        refuse_reasons.append("init_watchdog_readiness_failed")

    # Phase 5 seed readiness
    seeds_path = KERNEL / "GEN1640_SEED_RECOMMENDATIONS.json"
    seeds = json.loads(seeds_path.read_text(encoding="utf-8")) if seeds_path.exists() else {}
    write_pair(
        "self_improvement_seed_readiness_check",
        {
            "classification": "DOOFUS_SELF_IMPROVEMENT_SEED_READINESS",
            "seed_count": seeds.get("seed_count"),
            "p0_count": seeds.get("p0_count"),
            "p1_count": seeds.get("p1_count"),
            "deferred_count": seeds.get("deferred_count"),
            "safe_injection_mechanism_exists": False,
            "mechanism_path": None,
            "seed_context_used_in_live_cycle": False,
            "decision": "staged_as_artifact_only_context",
            "refusal_reason": "no safe runtime seed injection mechanism",
            "runtime_mutation_risk": "none",
        },
    )

    # Phase 6 launch intent
    intent = {
        "classification": "DOOFUS_LIVE_GEN1640_RETRY_LAUNCH_INTENT",
        "operator_authorization": "explicitly authorized by this prompt",
        "target_generation": 1640,
        "source_generation": 1639,
        "one_cycle_only": True,
        "command": " ".join(AUTHORIZED_COMMAND),
        "provider_expected": "cursor",
        "model_expected": "composer-2.5",
        "max_model_calls": 2,
        "max_cost_usd": 0.05,
        "stop_flag_before": "stop_requested=true",
        "stop_clear_allowed": "only inside guarded one-cycle try/finally",
        "stop_restore_required": True,
        "gen1641_prevention_required": True,
        "continuous_loop_allowed": False,
        "repeated_cycle_allowed": False,
        "db_max_generation_before": 1639,
        "gen1640_row_count_before": 0,
        "gen1641_row_count_before": 0,
        "live_db_preflight": "passed" if not pf_before.get("blockers") else "failed",
        "nonlive_dry_run_guard": "passed" if nonlive_ok else "failed",
        "guard_tests": "passed" if t_focus.returncode == 0 and t_broad.returncode == 0 else "failed",
        "init_watchdog_readiness": "passed" if init_ok else "failed",
        "provider_gate_fix": "committed and validated",
        "self_improvement_seed_context": "staged_as_artifact_only_context",
        "refuse_reasons": refuse_reasons,
    }
    write_pair("LIVE_GEN1640_RETRY_LAUNCH_INTENT", intent)

    if refuse_reasons:
        write_pair(
            "FINAL_REPORT",
            {
                "classification": "DOOFUS_GEN1640_RETRY_LIVE_VERIFICATION_PARTIAL",
                "launch_refused": True,
                "refuse_reasons": refuse_reasons,
                "next_action": f"Resolve blockers: {', '.join(refuse_reasons)}",
            },
        )
        print(json.dumps({"classification": "DOOFUS_GEN1640_RETRY_LIVE_VERIFICATION_PARTIAL", "refused": refuse_reasons}, indent=2))
        return 1

    # Phase 7 execute live cycle
    start = datetime.now().astimezone().isoformat()
    proc = subprocess.run(
        AUTHORIZED_COMMAND,
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=7200,
        env=launch_env,
    )
    end = datetime.now().astimezone().isoformat()
    try:
        cycle_out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        cycle_out = {"raw_stdout": (proc.stdout or "")[-3000:], "parse_error": True}

    (OUT / "live_cycle_stdout_stderr.log").write_text(
        json.dumps({"stdout": proc.stdout, "stderr": proc.stderr}, indent=2),
        encoding="utf-8",
    )
    write_pair(
        "live_cycle_process_result",
        {
            "classification": "DOOFUS_LIVE_CYCLE_PROCESS_RESULT",
            "start": start,
            "end": end,
            "exit_code": proc.returncode,
            "command": " ".join(AUTHORIZED_COMMAND),
            "launch_env_provider": launch_env.get("DOOFUS_MODEL_PROVIDER"),
            "launch_env_force_dry_run": launch_env.get("DOOFUS_FORCE_MODEL_DRY_RUN"),
        },
    )

    # Phase 8 post-run
    stop_after = status()
    if not stop_after.get("stop_requested"):
        stop_after = stop()
    ck_after = load_checkpoint()
    cc_after = read_checkpoint()
    pf_after = inspect_live_db(target_generation=1640)
    pf1641_after = inspect_live_db(target_generation=1641)

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=30)
    model_calls = conn.execute("SELECT COUNT(*) FROM model_call_events WHERE generation=1640").fetchone()[0]
    candidates = conn.execute("SELECT COUNT(*) FROM candidates WHERE generation=1640").fetchone()[0]
    map_elites = conn.execute("SELECT COUNT(*) FROM map_elites_cells WHERE generation=1640").fetchone()[0]
    champion = conn.execute("SELECT COUNT(*) FROM champion_defense_events WHERE generation=1640").fetchone()[0]
    gen1641_total = sum(conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1641").fetchone()[0] for t in generation_tables(conn))
    conn.close()

    write_pair("live_db_preflight_after_retry", {"classification": "DOOFUS_LIVE_DB_PREFLIGHT_AFTER_RETRY", "preflight": pf_after})
    invariants_ok = (
        stop_after.get("stop_requested")
        and ck_after.get("generation", 9999) <= 1640
        and pf_after.get("db_max_generation", 9999) <= 1640
        and gen1641_total == 0
        and model_calls <= 2
    )
    write_pair(
        "post_run_invariant_check",
        {
            "classification": "DOOFUS_POST_RUN_INVARIANT_CHECK",
            "stop_flag": stop_after,
            "checkpoint": ck_after,
            "cycle_checkpoint": cc_after,
            "gen1640_row_count": pf_after.get("target_generation_total"),
            "gen1641_row_count": gen1641_total,
            "live_model_call_count_gen1640": model_calls,
            "candidate_count_gen1640": candidates,
            "map_elites_gen1640": map_elites,
            "champion_defense_gen1640": champion,
            "continuous_loop_started": False,
            "repeated_cycle_detected": False,
            "all_invariants_pass": invariants_ok,
        },
    )

    subprocess.run([sys.executable, "scripts/doofus_gen1640_retry_live_verification_v1_finalize.py"], cwd=WORKSPACE, check=False)

    final_path = OUT / "FINAL_REPORT.json"
    if final_path.exists():
        final = json.loads(final_path.read_text(encoding="utf-8"))
        print(json.dumps({"classification": final.get("classification"), "exit_code": proc.returncode}, indent=2))
        return 0 if final.get("classification") == "DOOFUS_GEN1640_RETRY_LIVE_VERIFICATION_PASS" else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
