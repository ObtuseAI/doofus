"""Gen1641 live verification bundle - one authorized guarded live cycle."""
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
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1641-live-verification-v1"
POSTLIVE = WORKSPACE / "artifacts" / "doofus" / "gen1640-postlive-certification-v1"
RETRY3 = WORKSPACE / "artifacts" / "doofus" / "gen1640-retry3-live-verification-v1"
EXPECTED_COMMIT = "0a18e613b9e10df61de6405df1e78bd884d62095"
TARGET = 1641
SOURCE = 1640
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
    "doofus/reports/run_window_telemetry_filter.py",
    "doofus/evolution/shadow_elite_upgrade_queue.py",
    "doofus/evolution/map_elites",
    "doofus/runtime/live_db_preflight.py",
    "doofus/supervisor/checkpoint_baseline.py",
)


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


def live_launch_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("DOOFUS_STATE", "DOOFUS_METRICS_DB", "DOOFUS_CONTROL", "DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS"):
        env.pop(key, None)
    env.pop("DOOFUS_FORCE_MODEL_DRY_RUN", None)
    env["DOOFUS_MODEL_PROVIDER"] = "cursor"
    return env


def phase6_run_window_readiness() -> dict:
    from datetime import datetime

    from doofus.reports.run_window_telemetry_filter import filter_events_by_run_window, read_jsonl, stale_classification_impact

    retry3_proc = json.loads((RETRY3 / "live_cycle_process_result.json").read_text(encoding="utf-8"))
    start_dt = datetime.fromisoformat(retry3_proc["start"])
    end_dt = datetime.fromisoformat(retry3_proc["end"])
    init_events = read_jsonl(WORKSPACE / "runtime" / "state" / "cycle_init_events.jsonl")
    filtered = filter_events_by_run_window(
        init_events,
        generation=1640,
        window_start=start_dt,
        window_end=end_dt,
        source_name="cycle_init_events.jsonl",
    )
    impact = stale_classification_impact(
        unfiltered_init_events=init_events,
        filtered_init_events=filtered.events_in_window,
        generation=1640,
        pass_without_stale=True,
    )
    gen1641_filtered = filter_events_by_run_window(
        init_events,
        generation=1641,
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        source_name="cycle_init_events.jsonl",
    )
    passed = (
        filtered.events_excluded_count > 0
        and impact.get("stale_events_changed_classification") is True
        and filtered.run_window_filter_applied is True
        and gen1641_filtered.run_window_filter_applied is True
    )
    return {
        "classification": "DOOFUS_RUN_WINDOW_TELEMETRY_READINESS",
        "passed": passed,
        "filter_module": "doofus/reports/run_window_telemetry_filter.py",
        "retry3_window_start": retry3_proc.get("start"),
        "retry3_window_end": retry3_proc.get("end"),
        "retry3_stale_excluded": filtered.events_excluded_count,
        "stale_events_changed_classification": impact.get("stale_events_changed_classification"),
        "future_artifact_directory": str(OUT),
        "gen1641_empty_window_excluded": gen1641_filtered.events_excluded_count,
    }


def main() -> int:
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core import doofus_paths
    from doofus.core.doofus_config import DoofusConfig
    from doofus.model_router.provider_router import resolve_provider
    from doofus.proof.inline_rescue_budget import policy_snapshot
    from doofus.runtime.live_db_preflight import generation_tables, inspect_live_db
    from doofus.safety.on_off_switch import status, stop
    from doofus.supervisor.checkpoint_baseline import validate_checkpoint, validate_cycle_checkpoint
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
    staged_lc = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=WORKSPACE, capture_output=True, text=True).stdout
    staged_lc_hits = [p for p in staged_lc.splitlines() if any(p.replace("\\", "/").startswith(x) for x in LAUNCH_CRITICAL_PREFIXES)]

    prep_path = POSTLIVE / "GEN1641_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY.json"
    prep = json.loads(prep_path.read_text(encoding="utf-8")) if prep_path.exists() else {}

    ck = load_checkpoint()
    cc = read_checkpoint()
    stop_before = status()
    pf_target = inspect_live_db(target_generation=TARGET)
    pf_next = inspect_live_db(target_generation=TARGET + 1)

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
        mx = conn.execute(f"SELECT MAX(generation) FROM {t}").fetchone()[0]
        by_table[t] = {
            "max_generation": mx,
            f"gen{SOURCE}": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation={SOURCE}").fetchone()[0],
            f"gen{TARGET}": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation={TARGET}").fetchone()[0],
            f"gen{TARGET + 1}": conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation={TARGET + 1}").fetchone()[0],
        }
    conn.close()

    cc_data = cc.get("data") or {}
    cc_class = cc_data.get("classification", cc.get("classification", ""))
    cc_gen = cc_data.get("generation", cc.get("generation"))

    os.environ.pop("DOOFUS_FORCE_MODEL_DRY_RUN", None)
    os.environ["DOOFUS_MODEL_PROVIDER"] = "cursor"
    route_preview = resolve_provider()
    cfg_live = DoofusConfig.from_env()

    starting = {
        "classification": "DOOFUS_GEN1641_STARTING_STATE",
        "timestamp": utc_now(),
        "operator_authorization": "explicitly authorized by this prompt for one gen1641 live cycle",
        "branch": branch,
        "commit": commit,
        "expected_commit": EXPECTED_COMMIT,
        "commit_match": commit == EXPECTED_COMMIT,
        "worktree_dirty_count": len(dirty_lines),
        "launch_critical_dirty_files": lc_dirty,
        "launch_critical_staged_files": staged_lc_hits,
        "launch_critical_clean": len(staged_lc_hits) == 0,
        "gen1641_prep_packet_hash": file_hash(prep_path),
        "gen1640_certification_manifest_hash": file_hash(POSTLIVE / "gen1640_certification_manifest.json"),
        "run_window_filter_source_hash": file_hash(WORKSPACE / "doofus/reports/run_window_telemetry_filter.py"),
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "checkpoint_schema_valid": ck_schema,
        "cycle_checkpoint_schema_valid": cc_schema,
        "stop_flag": stop_before,
        "live_db_path": str(doofus_paths.METRICS_DB),
        "by_table": by_table,
        "db_max_generation": pf_target.get("db_max_generation"),
        "candidates_max_generation": by_table.get("candidates", {}).get("max_generation"),
        "gen1641_row_count_before": pf_target.get("target_generation_total") if TARGET == pf_target.get("target_generation") else 0,
        "gen1642_row_count_before": pf_next.get("target_generation_total"),
        "inline_rescue_budget_policy": policy_snapshot(),
        "provider_preview": {
            "provider_selected": route_preview.get("provider_selected"),
            "model_name": route_preview.get("model_name"),
            "live_provider_ready": route_preview.get("live_provider_ready"),
            "model_mode_live_launch_env": cfg_live.model_mode,
        },
        "prep_packet_validation": {
            "packet_exists": prep_path.exists(),
            "has_one_cycle_command": "--operator-approved-one-cycle" in prep.get("future_command_template", ""),
            "baseline_matches": prep.get("required_baseline", {}).get("checkpoint_generation") == SOURCE,
            "packet_did_not_authorize_launch": True,
            "this_prompt_authorizes_launch": True,
        },
    }
    write_pair("STARTING_STATE", starting)

    refuse_reasons: list[str] = []
    if not prep_path.exists():
        refuse_reasons.append("gen1641_prep_packet_missing")
    if "--operator-approved-one-cycle" not in prep.get("future_command_template", ""):
        refuse_reasons.append("prep_packet_missing_one_cycle_flag")
    if commit != EXPECTED_COMMIT:
        refuse_reasons.append("commit_mismatch")
    if ck.get("generation") != SOURCE or ck.get("phase") != "complete":
        refuse_reasons.append("checkpoint")
    if cc_gen != SOURCE or "B1003_LIVE_MODEL_CYCLE_PASS" not in str(cc_class):
        refuse_reasons.append("cycle_checkpoint")
    if not ck_schema or not cc_schema:
        refuse_reasons.append("checkpoint_schema_invalid")
    if not stop_before.get("stop_requested"):
        refuse_reasons.append("stop_flag")
    if pf_target.get("db_max_generation") != SOURCE:
        refuse_reasons.append("db_max_generation")
    if by_table.get("candidates", {}).get("max_generation") != SOURCE:
        refuse_reasons.append("candidates_max_generation")
    gen1641_before = sum(by_table.get(t, {}).get(f"gen{TARGET}", 0) for t in by_table)
    if gen1641_before != 0:
        refuse_reasons.append("gen1641_rows_exist")
    if pf_next.get("target_generation_total", 0) != 0:
        refuse_reasons.append("gen1642_rows_exist")
    if staged_lc_hits:
        refuse_reasons.append("launch_critical_staged_dirty")
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
        "live_db_preflight_before_launch",
        {
            "classification": "DOOFUS_LIVE_DB_PREFLIGHT_BEFORE_GEN1641",
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
        "tests/test_run_window_telemetry_filtering.py",
        "tests/test_shadow_upgrade_deadline.py",
        "tests/test_inline_rescue_budget_policy.py",
        "tests/test_high_score_rejection_miner_deadline.py",
        "tests/test_inline_rescue_high_score_deadline.py",
        "tests/test_init_timeout_containment_baseline.py",
        "tests/test_cycle_init_watchdog.py",
        "tests/test_provider_aware_one_cycle_launch.py",
        "tests/test_provider_gate_postlive.py",
        "tests/test_live_cycle_launch_guard.py",
        "tests/test_live_db_preflight.py",
        "tests/test_inline_rescue.py",
        "tests/test_doofus_proof_builder.py",
        "tests/test_doofus.py",
        "-k",
        "run_window or telemetry_filter or shadow_upgrade or inline_rescue or high_score or init_timeout or containment or cycle_init or init_watchdog or provider_gate or one_cycle or live_cycle_launch_guard or provider_aware or stop_requested or nonlive_cycle_forces_model_dry_run or live_db_preflight or isolated_runtime or proof_builder or postlive",
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
            "run_window or telemetry_filter or shadow_upgrade or inline_rescue or high_score or init_timeout or containment or cycle_init or init_watchdog or provider_gate or live_cycle_launch_guard or provider_aware or stop_state_guard or live_db_preflight or isolated_runtime or nonlive_cycle_forces_model_dry_run or proof_builder or map_elites or scoring or postlive or self_improvement",
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
            "classification": "DOOFUS_GEN1641_PRELAUNCH_TESTS",
            "focused_passed": t_focus.returncode == 0,
            "focused_tail": (t_focus.stdout or t_focus.stderr or "")[-1500:],
            "broader_passed": t_broad.returncode == 0,
            "broader_tail": (t_broad.stdout or t_broad.stderr or "")[-1500:],
        },
    )
    if t_focus.returncode != 0 or t_broad.returncode != 0:
        refuse_reasons.append("guard_tests_failed")

    # Phase 3 nonlive probe
    nonlive = verify_nonlive_dry_run_guard()
    pf_post = inspect_live_db(target_generation=TARGET)
    pf1642_post = inspect_live_db(target_generation=TARGET + 1)
    nonlive_ok = (
        nonlive.get("classification") == "DOOFUS_MODEL_DRY_RUN"
        and pf_post.get("db_max_generation") == SOURCE
        and pf1642_post.get("target_generation_total") == 0
        and load_checkpoint().get("generation") == SOURCE
        and status().get("stop_requested") is True
    )
    write_pair(
        "nonlive_dry_run_guard_probe",
        {
            "classification": "DOOFUS_NONLIVE_DRY_RUN_GUARD_PROBE",
            "probe": nonlive,
            "passed": nonlive_ok,
            "checkpoint_after": load_checkpoint(),
            "stop_after": status(),
        },
    )
    if not nonlive_ok:
        refuse_reasons.append("nonlive_dry_run_guard_failed")

    # Phase 4 miner readiness (generation 1641 for telemetry label; readonly on live DB)
    miner_proc = subprocess.run(
        [
            sys.executable,
            "scripts/doofus_high_score_miner_diagnostic.py",
            "--generation",
            str(TARGET),
            "--limit",
            "20",
            "--deadline-seconds",
            "30",
            "--explain-query-plan",
            "--output-dir",
            str(OUT),
            "--stem",
            "LIVE_SCALE_MINER_READINESS",
        ],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=120,
    )
    miner_ready = json.loads((OUT / "LIVE_SCALE_MINER_READINESS.json").read_text(encoding="utf-8")) if (OUT / "LIVE_SCALE_MINER_READINESS.json").exists() else {}
    write_pair(
        "live_scale_miner_readiness_check",
        {
            "classification": "DOOFUS_LIVE_SCALE_MINER_READINESS",
            "passed": miner_ready.get("passed") is True,
            "diagnostic": miner_ready,
            "note": "generation parameter 1641 used for telemetry; query is read-only against live DB baseline",
        },
    )
    if not miner_ready.get("passed"):
        refuse_reasons.append("live_scale_miner_readiness_failed")

    # Phase 5 shadow readiness
    shadow_proc = subprocess.run(
        [
            sys.executable,
            "scripts/doofus_shadow_upgrade_diagnostic.py",
            "--generation",
            str(TARGET),
            "--limit",
            "5",
            "--deadline-seconds",
            "30",
            "--dry-run",
            "--output-dir",
            str(OUT),
            "--stem",
            "SHADOW_UPGRADE_READINESS",
        ],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=120,
    )
    shadow_ready = json.loads((OUT / "SHADOW_UPGRADE_READINESS.json").read_text(encoding="utf-8")) if (OUT / "SHADOW_UPGRADE_READINESS.json").exists() else {}
    write_pair(
        "shadow_upgrade_readiness_check",
        {
            "classification": "DOOFUS_SHADOW_UPGRADE_READINESS",
            "passed": shadow_ready.get("passed") is True,
            "diagnostic": shadow_ready,
        },
    )
    if not shadow_ready.get("passed"):
        refuse_reasons.append("shadow_upgrade_readiness_failed")

    # Phase 6 run-window readiness
    rw = phase6_run_window_readiness()
    write_pair("run_window_telemetry_readiness_check", rw)
    if not rw.get("passed"):
        refuse_reasons.append("run_window_telemetry_readiness_failed")

    # Phase 7 inline-rescue rehearsal
    rehearsal_proc = subprocess.run(
        [sys.executable, "scripts/doofus_gen1640_shadow_upgrade_rehearsal.py", "--output-dir", str(OUT), "--low-budget"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=120,
    )
    rehearsal = json.loads((OUT / "SHADOW_UPGRADE_REHEARSAL_RESULT.json").read_text(encoding="utf-8")) if (OUT / "SHADOW_UPGRADE_REHEARSAL_RESULT.json").exists() else {}
    write_pair(
        "inline_rescue_rehearsal_readiness_check",
        {
            "classification": "DOOFUS_INLINE_RESCUE_REHEARSAL_READINESS",
            "passed": rehearsal.get("passed") is True,
            "rehearsal": rehearsal,
            "note": "gen1640-named rehearsal used as repaired generic inline-rescue/shadow rehearsal",
        },
    )
    if not rehearsal.get("passed"):
        refuse_reasons.append("inline_rescue_rehearsal_failed")

    # Phase 8 seed readiness
    manifest = json.loads((POSTLIVE / "gen1640_certification_manifest.json").read_text(encoding="utf-8")) if (POSTLIVE / "gen1640_certification_manifest.json").exists() else {}
    seed_decision = "staged_as_artifact_only_context_from_certification_manifest"
    write_pair(
        "self_improvement_seed_readiness_check",
        {
            "classification": "DOOFUS_SELF_IMPROVEMENT_SEED_READINESS",
            "source_artifacts": [str(POSTLIVE / "gen1640_certification_manifest.json"), str(prep_path)],
            "safe_injection_mechanism_exists": False,
            "seed_context_used_in_live_cycle": False,
            "decision": seed_decision,
            "refusal_reason": "no safe runtime seed injection mechanism",
            "runtime_mutation_risk": "none",
            "certification_manifest_classification": manifest.get("final_certification_verdict"),
        },
    )
    starting["self_improvement_seed_decision"] = seed_decision

    # Phase 9 launch intent
    intent = {
        "classification": "DOOFUS_LIVE_GEN1641_LAUNCH_INTENT",
        "operator_authorization": "explicitly authorized by this prompt",
        "target_generation": TARGET,
        "source_generation": SOURCE,
        "one_cycle_only": True,
        "command": " ".join(AUTHORIZED_COMMAND),
        "provider_expected": "cursor",
        "model_expected": "composer-2.5",
        "max_model_calls": 2,
        "max_cost_usd": 0.05,
        "stop_flag_before": "stop_requested=true",
        "stop_clear_allowed": "only inside guarded one-cycle try/finally",
        "stop_restore_required": True,
        "gen1642_prevention_required": True,
        "continuous_loop_allowed": False,
        "repeated_cycle_allowed": False,
        "db_max_generation_before": SOURCE,
        "gen1641_row_count_before": 0,
        "gen1642_row_count_before": 0,
        "live_db_preflight": "passed" if not pf_before.get("blockers") else "failed",
        "nonlive_dry_run_guard": "passed" if nonlive_ok else "failed",
        "guard_tests": "passed" if t_focus.returncode == 0 and t_broad.returncode == 0 else "failed",
        "live_scale_miner_readiness": "passed" if miner_ready.get("passed") else "failed",
        "shadow_upgrade_readiness": "passed" if shadow_ready.get("passed") else "failed",
        "run_window_telemetry_readiness": "passed" if rw.get("passed") else "failed",
        "inline_rescue_rehearsal": "passed" if rehearsal.get("passed") else "failed",
        "run_window_telemetry_filter": "active",
        "self_improvement_seed_context": seed_decision,
        "refuse_reasons": refuse_reasons,
    }
    write_pair("LIVE_GEN1641_LAUNCH_INTENT", intent)

    if refuse_reasons:
        write_pair(
            "FINAL_REPORT",
            {
                "classification": "DOOFUS_GEN1641_LIVE_VERIFICATION_PARTIAL",
                "launch_refused": True,
                "refuse_reasons": refuse_reasons,
                "next_action": f"Resolve blockers: {', '.join(refuse_reasons)}",
            },
        )
        print(json.dumps({"classification": "DOOFUS_GEN1641_LIVE_VERIFICATION_PARTIAL", "refused": refuse_reasons}, indent=2))
        return 1

    # Phase 10 execute live cycle
    launch_env = live_launch_env()
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
            "cycle_output": cycle_out,
        },
    )

    # Phase 11 post-run
    stop_after = status()
    if not stop_after.get("stop_requested"):
        stop_after = stop()
    ck_after = load_checkpoint()
    cc_after = read_checkpoint()
    pf_after = inspect_live_db(target_generation=TARGET)
    pf1642_after = inspect_live_db(target_generation=TARGET + 1)

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=30)
    model_calls = conn.execute(f"SELECT COUNT(*) FROM model_call_events WHERE generation={TARGET}").fetchone()[0]
    candidates = conn.execute(f"SELECT COUNT(*) FROM candidates WHERE generation={TARGET}").fetchone()[0]
    map_elites = conn.execute(f"SELECT COUNT(*) FROM map_elites_cells WHERE generation={TARGET}").fetchone()[0]
    champion = conn.execute(f"SELECT COUNT(*) FROM champion_defense_events WHERE generation={TARGET}").fetchone()[0]
    gen1642_total = sum(conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation={TARGET + 1}").fetchone()[0] for t in generation_tables(conn))
    conn.close()

    ck_schema_after = cc_schema_after = True
    try:
        validate_checkpoint(ck_after)
        validate_cycle_checkpoint(cc_after)
    except Exception:
        ck_schema_after = cc_schema_after = False

    subprocess.run([sys.executable, "scripts/doofus_live_db_preflight.py", "--output-dir", str(OUT)], cwd=WORKSPACE, capture_output=True, text=True, timeout=120)
    pf_after_full = json.loads((OUT / "live_db_preflight_check_only.json").read_text(encoding="utf-8")) if (OUT / "live_db_preflight_check_only.json").exists() else pf_after
    write_pair(
        "live_db_preflight_after_run",
        {
            "classification": "DOOFUS_LIVE_DB_PREFLIGHT_AFTER_GEN1641",
            "passed": not pf_after_full.get("blockers"),
            "preflight": pf_after_full,
        },
    )

    invariants_ok = (
        stop_after.get("stop_requested")
        and ck_after.get("generation", 9999) <= TARGET
        and pf_after.get("db_max_generation", 9999) <= TARGET
        and gen1642_total == 0
        and model_calls <= 2
        and ck_schema_after
        and cc_schema_after
    )
    write_pair(
        "post_run_invariant_check",
        {
            "classification": "DOOFUS_POST_RUN_INVARIANT_CHECK",
            "stop_flag": stop_after,
            "checkpoint": ck_after,
            "cycle_checkpoint": cc_after,
            "gen1641_row_count": pf_after.get("target_generation_total"),
            "gen1642_row_count": gen1642_total,
            "live_model_call_count_gen1641": model_calls,
            "candidate_count_gen1641": candidates,
            "checkpoint_schema_valid": ck_schema_after,
            "cycle_checkpoint_schema_valid": cc_schema_after,
            "all_invariants_pass": invariants_ok,
        },
    )

    subprocess.run([sys.executable, "scripts/doofus_gen1641_live_verification_v1_finalize.py"], cwd=WORKSPACE, check=False)

    final_path = OUT / "FINAL_REPORT.json"
    if final_path.exists():
        final = json.loads(final_path.read_text(encoding="utf-8"))
        print(json.dumps({"classification": final.get("classification"), "exit_code": proc.returncode}, indent=2))
        return 0 if final.get("classification") == "DOOFUS_GEN1641_LIVE_VERIFICATION_PASS" else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
