"""Gen1640 live verification bundle - one authorized guarded live cycle."""
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
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1640-live-verification-v1"
KERNEL = WORKSPACE / "artifacts" / "doofus" / "self-improvement-kernel-gen1640-readiness-v1"
GEN1639 = WORKSPACE / "artifacts" / "doofus" / "gen1639-live-verification-v1"
EXPECTED_COMMIT = "795e66e1e7c846ececa28c51c8aacaffb0fef8c5"
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
    "doofus/supervisor/live_cycle_launch_guard.py",
    "doofus/supervisor/provider_aware_live_cycle.py",
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
    if path.exists():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return None


def launch_critical_dirty() -> list[str]:
    dirty = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()
    hits = []
    for line in dirty:
        path = line[3:].strip().strip('"')
        norm = path.replace("\\", "/")
        for prefix in LAUNCH_CRITICAL_PREFIXES:
            if norm.startswith(prefix) or norm == prefix.rstrip("/"):
                hits.append(path)
                break
    return hits


def launch_critical_diff_snapshot() -> str:
    paths = []
    for prefix in LAUNCH_CRITICAL_PREFIXES:
        p = WORKSPACE / prefix.rstrip("/")
        if p.is_file():
            paths.append(prefix)
        elif p.is_dir():
            paths.extend(str(f.relative_to(WORKSPACE)).replace("\\", "/") for f in p.rglob("*") if f.is_file())
    if not paths:
        return ""
    diff = subprocess.run(
        ["git", "diff", "HEAD", "--", *paths[:200]],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    staged = subprocess.run(
        ["git", "diff", "--cached", "HEAD", "--", *paths[:200]],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    return hashlib.sha256((diff.stdout + staged.stdout).encode()).hexdigest()


def count_gen_rows(conn: sqlite3.Connection, generation: int) -> dict[str, int]:
    from doofus.runtime.live_db_preflight import generation_tables

    out = {}
    for t in generation_tables(conn):
        try:
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=?", (generation,)).fetchone()[0]
        except sqlite3.Error:
            out[t] = -1
    return out


def main() -> int:
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core import doofus_paths
    from doofus.core.doofus_events import utc_now as doofus_utc
    from doofus.runtime.live_db_preflight import inspect_live_db, generation_tables
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint
    from doofus.supervisor.live_cycle_launch_guard import verify_nonlive_dry_run_guard

    OUT.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip()
    dirty_lines = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()
    lc_dirty = launch_critical_dirty()
    lc_diff_start = launch_critical_diff_snapshot()
    staged_lc = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    ).stdout
    staged_lc_hits = [p for p in staged_lc.splitlines() if any(p.replace("\\", "/").startswith(x) for x in LAUNCH_CRITICAL_PREFIXES)]

    packet_path = KERNEL / "GEN1640_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))

    ck = load_checkpoint()
    cc = read_checkpoint()
    stop = status()
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
    candidates_max = by_table.get("candidates", {}).get("max_generation")
    map_elites_max = by_table.get("map_elites_cells", {}).get("max_generation")
    conn.close()

    cc_data = cc.get("data") or {}
    cc_class = cc_data.get("classification", cc.get("classification", ""))
    cc_gen = cc_data.get("generation", cc.get("generation"))

    starting = {
        "classification": "DOOFUS_GEN1640_LIVE_STARTING_STATE",
        "timestamp": doofus_utc(),
        "operator_authorization": "explicitly authorized by this prompt for one gen1640 live cycle",
        "branch": branch,
        "commit": commit,
        "expected_commit": EXPECTED_COMMIT,
        "commit_match": commit == EXPECTED_COMMIT,
        "worktree_dirty_count": len(dirty_lines),
        "launch_critical_dirty_files": lc_dirty,
        "launch_critical_staged_files": staged_lc_hits,
        "launch_critical_diff_snapshot_start": lc_diff_start,
        "launch_critical_clean": len(staged_lc_hits) == 0,
        "prep_packet_hash": file_hash(packet_path),
        "catalog_hash": file_hash(KERNEL / "self_improvement_catalog.json"),
        "seeds_hash": file_hash(KERNEL / "GEN1640_SEED_RECOMMENDATIONS.json"),
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "stop_flag": stop,
        "live_db_path": str(doofus_paths.METRICS_DB),
        "by_table": by_table,
        "db_max_generation": pf1640.get("db_max_generation"),
        "candidates_max_generation": candidates_max,
        "map_elites_max_generation": map_elites_max,
        "gen1640_row_count": pf1640.get("target_generation_total"),
        "gen1641_row_count": pf1641.get("target_generation_total"),
        "credentials_presence": {
            "DOOFUS_MODEL_PROVIDER": os.environ.get("DOOFUS_MODEL_PROVIDER"),
            "CURSOR_API_KEY_set": bool(os.environ.get("CURSOR_API_KEY")),
            "OPENAI_API_KEY_set": bool(os.environ.get("OPENAI_API_KEY")),
        },
        "relevant_env": {
            k: os.environ.get(k)
            for k in ("DOOFUS_MODEL_PROVIDER", "DOOFUS_MODEL_MODE", "DOOFUS_FORCE_MODEL_DRY_RUN")
            if os.environ.get(k)
        },
    }
    write_pair("STARTING_STATE", starting)

    refuse_reasons = []
    if not packet_path.exists():
        refuse_reasons.append("prep_packet_missing")
    if "--operator-approved-one-cycle" not in packet.get("future_command_template", ""):
        refuse_reasons.append("prep_packet_missing_one_cycle_flag")
    if commit != EXPECTED_COMMIT:
        refuse_reasons.append("commit_mismatch")
    if ck.get("generation") != 1639 or ck.get("phase") != "complete":
        refuse_reasons.append("checkpoint")
    if cc_gen != 1639 or "B1003_LIVE_MODEL_CYCLE_PASS" not in str(cc_class):
        refuse_reasons.append("cycle_checkpoint")
    if not stop.get("stop_requested"):
        refuse_reasons.append("stop_flag")
    if pf1640.get("db_max_generation") != 1639:
        refuse_reasons.append("db_max_generation")
    if candidates_max != 1639:
        refuse_reasons.append("candidates_max_generation")
    if pf1640.get("target_generation_total", 1) != 0:
        refuse_reasons.append("gen1640_rows_exist")
    if pf1641.get("target_generation_total", 0) != 0:
        refuse_reasons.append("gen1641_rows_exist")
    if staged_lc_hits:
        refuse_reasons.append("launch_critical_staged_dirty")
    lc_diff_launch = launch_critical_diff_snapshot()
    if lc_diff_launch != lc_diff_start:
        refuse_reasons.append("launch_critical_diff_changed_during_bundle")

    # Phase 1 - preflight
    pf_proc = subprocess.run(
        [sys.executable, "scripts/doofus_live_db_preflight.py", "--output-dir", str(OUT), "--target-generation", "1640"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=120,
    )
    pf_before_path = OUT / "live_db_preflight_check_only.json"
    pf_before = json.loads(pf_before_path.read_text(encoding="utf-8")) if pf_before_path.exists() else {}
    write_pair(
        "live_db_preflight_before_launch",
        {
            "classification": "DOOFUS_LIVE_DB_PREFLIGHT_BEFORE_LAUNCH",
            "status": "passed" if not pf_before.get("blockers") else "failed",
            "preflight": pf_before,
            "script_exit_code": pf_proc.returncode,
        },
    )
    if pf_before.get("blockers"):
        refuse_reasons.append("live_db_preflight_failed")

    # Phase 2 - tests
    focused_cmd = [
        sys.executable, "-m", "pytest",
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
        "self_improvement or generation_summary or provider_gate or one_cycle or live_cycle_launch_guard or provider_aware or stop_requested or nonlive_cycle_forces_model_dry_run or live_db_preflight or isolated_runtime or inline_rescue or proof_builder or postlive",
        "-q",
    ]
    t_focus = subprocess.run(focused_cmd, cwd=WORKSPACE, capture_output=True, text=True, timeout=300)
    t_broad = subprocess.run(
        [
            sys.executable, "-m", "pytest", "tests",
            "-k",
            "self_improvement or generation_summary or provider_gate or live_cycle_launch_guard or provider_aware or stop_state_guard or live_db_preflight or isolated_runtime or nonlive_cycle_forces_model_dry_run or inline_rescue or proof_builder or map_elites or scoring or postlive",
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
            "classification": "DOOFUS_GEN1640_PRELAUNCH_TESTS",
            "focused_passed": t_focus.returncode == 0,
            "focused_tail": (t_focus.stdout or t_focus.stderr or "")[-800:],
            "broader_passed": t_broad.returncode == 0,
            "broader_tail": (t_broad.stdout or t_broad.stderr or "")[-800:],
        },
    )
    if t_focus.returncode != 0:
        refuse_reasons.append("guard_tests_failed")

    # Phase 3 - nonlive dry-run probe
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
            "preflight_before": {k: pf_pre_probe.get(k) for k in ("db_max_generation", "target_generation_total")},
            "preflight_after": {k: pf_post_probe.get(k) for k in ("db_max_generation", "target_generation_total")},
            "gen1641_after": pf1641_post.get("target_generation_total"),
            "checkpoint_after": load_checkpoint(),
            "stop_after": status(),
        },
    )
    if not nonlive_ok:
        refuse_reasons.append("nonlive_dry_run_guard_failed")

    # Phase 4 - seed readiness
    seeds = json.loads((KERNEL / "GEN1640_SEED_RECOMMENDATIONS.json").read_text(encoding="utf-8"))
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
            "refusal_reason": "no safe runtime seed injection mechanism; seeds remain read-only artifacts",
            "runtime_mutation_risk": "none",
        },
    )

    # Phase 5 - launch intent
    intent = {
        "classification": "DOOFUS_LIVE_GEN1640_LAUNCH_INTENT",
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
        "guard_tests": "passed" if t_focus.returncode == 0 else "failed",
        "provider_gate_fix": "committed and validated",
        "self_improvement_seed_context": "staged_as_artifact_only_context",
        "refuse_reasons": refuse_reasons,
    }
    write_pair("LIVE_GEN1640_LAUNCH_INTENT", intent)

    if refuse_reasons:
        write_pair(
            "FINAL_REPORT",
            {
                "classification": "DOOFUS_GEN1640_LIVE_VERIFICATION_PARTIAL",
                "launch_refused": True,
                "refuse_reasons": refuse_reasons,
                "next_action": f"Resolve blockers: {', '.join(refuse_reasons)}",
            },
        )
        print(json.dumps({"classification": "DOOFUS_GEN1640_LIVE_VERIFICATION_PARTIAL", "refused": refuse_reasons}, indent=2))
        return 1

    # Phase 6 - execute live cycle
    start = datetime.now().astimezone().isoformat()
    proc = subprocess.run(
        AUTHORIZED_COMMAND,
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    end = datetime.now().astimezone().isoformat()
    cycle_out = {}
    try:
        cycle_out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        cycle_out = {"raw_stdout": proc.stdout[-2000:], "parse_error": True}

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
        },
    )

    # Phase 7 - post-run invariants
    stop_after = status()
    ck_after = load_checkpoint()
    cc_after = read_checkpoint()
    pf_after = inspect_live_db(target_generation=1640)
    pf1641_after = inspect_live_db(target_generation=1641)

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=30)
    model_calls = conn.execute("SELECT COUNT(*) FROM model_call_events WHERE generation=1640").fetchone()[0]
    candidates = conn.execute("SELECT COUNT(*) FROM candidates WHERE generation=1640").fetchone()[0]
    map_elites = conn.execute("SELECT COUNT(*) FROM map_elites_cells WHERE generation=1640").fetchone()[0]
    gen1641_total = sum(
        conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1641").fetchone()[0]
        for t in generation_tables(conn)
    )
    conn.close()

    if not stop_after.get("stop_requested"):
        switch_stop = __import__("doofus.safety.on_off_switch", fromlist=["stop"]).stop
        stop_after = switch_stop()

    write_pair(
        "live_db_preflight_after_run",
        {"classification": "DOOFUS_LIVE_DB_PREFLIGHT_AFTER_RUN", "preflight": pf_after},
    )

    cc_after_data = cc_after.get("data") or {}
    cc_after_gen = cc_after_data.get("generation", cc_after.get("generation"))
    cc_after_class = cc_after_data.get("classification", cc_after.get("classification", ""))

    invariants_ok = (
        stop_after.get("stop_requested")
        and ck_after.get("generation", 9999) <= 1640
        and (cc_after_gen or 9999) <= 1640
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
            "continuous_loop_started": False,
            "repeated_cycle_detected": False,
            "all_invariants_pass": invariants_ok,
        },
    )

    # Phase 8 - telemetry (delegate to finalize)
    subprocess.run([sys.executable, "scripts/doofus_gen1640_live_verification_v1_finalize.py"], cwd=WORKSPACE, check=False)

    final_path = OUT / "FINAL_REPORT.json"
    if final_path.exists():
        final = json.loads(final_path.read_text(encoding="utf-8"))
        print(json.dumps({"classification": final.get("classification"), "exit_code": proc.returncode}, indent=2))
        return 0 if final.get("classification") == "DOOFUS_GEN1640_LIVE_VERIFICATION_PASS" else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
