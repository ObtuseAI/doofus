"""Shared phase runners for controlled-cycle certification and live verification."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[2]


def run_cmd(cmd: list[str], *, cwd: Path | None = None, timeout: int = 600, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd or WORKSPACE, capture_output=True, text=True, timeout=timeout, env=env)


def run_live_db_preflight(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    proc = run_cmd([sys.executable, "scripts/doofus_live_db_preflight.py", "--output-dir", str(output_dir)], timeout=120)
    path = output_dir / "live_db_preflight_check_only.json"
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"passed": not payload.get("blockers"), "preflight": payload, "exit_code": proc.returncode}


def run_guard_tests(*, focused: bool = True, broad: bool = True) -> dict[str, Any]:
    focused_cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_controlled_cycle_tooling.py",
        "tests/test_run_window_telemetry_filtering.py",
        "tests/test_candidate_quality.py",
        "tests/test_promotion_near_miss.py",
        "tests/test_proof_builder_handoff.py",
        "tests/test_shadow_upgrade_deadline.py",
        "tests/test_inline_rescue_budget_policy.py",
        "tests/test_high_score_rejection_miner_deadline.py",
        "tests/test_provider_aware_one_cycle_launch.py",
        "tests/test_live_cycle_launch_guard.py",
        "tests/test_live_db_preflight.py",
        "-q",
    ]
    t_focus = run_cmd(focused_cmd, timeout=600) if focused else None
    t_broad = None
    if broad:
        t_broad = run_cmd(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests",
                "-k",
                "controlled_cycle or candidate_quality or near_miss or proof_builder or run_window or shadow_upgrade or inline_rescue or high_score or provider_gate or live_cycle_launch_guard or live_db_preflight or postlive",
                "-q",
            ],
            timeout=600,
        )
    return {
        "focused_passed": t_focus.returncode == 0 if t_focus else None,
        "focused_tail": ((t_focus.stdout or t_focus.stderr or "")[-1500:] if t_focus else ""),
        "broader_passed": t_broad.returncode == 0 if t_broad else None,
        "broader_tail": ((t_broad.stdout or t_broad.stderr or "")[-1500:] if t_broad else ""),
    }


def run_nonlive_dry_run_probe() -> dict[str, Any]:
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.live_cycle_launch_guard import verify_nonlive_dry_run_guard
    from doofus.safety.on_off_switch import status

    nonlive = verify_nonlive_dry_run_guard()
    pf = inspect_live_db(target_generation=1642)
    return {
        "probe": nonlive,
        "passed": nonlive.get("classification") == "DOOFUS_MODEL_DRY_RUN",
        "checkpoint_after": load_checkpoint(),
        "stop_after": status(),
        "db_max_generation": pf.get("db_max_generation"),
    }


def run_miner_readiness(generation: int, output_dir: Path, *, stem: str = "MINER_READINESS") -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    proc = run_cmd(
        [
            sys.executable,
            "scripts/doofus_high_score_miner_diagnostic.py",
            "--generation",
            str(generation),
            "--limit",
            "20",
            "--deadline-seconds",
            "30",
            "--explain-query-plan",
            "--output-dir",
            str(output_dir),
            "--stem",
            stem,
        ],
        timeout=120,
    )
    path = output_dir / f"{stem}.json"
    diagnostic = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"passed": diagnostic.get("passed") is True, "diagnostic": diagnostic, "exit_code": proc.returncode}


def run_shadow_readiness(generation: int, output_dir: Path, *, stem: str = "SHADOW_READINESS") -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    proc = run_cmd(
        [
            sys.executable,
            "scripts/doofus_shadow_upgrade_diagnostic.py",
            "--generation",
            str(generation),
            "--limit",
            "5",
            "--deadline-seconds",
            "30",
            "--dry-run",
            "--output-dir",
            str(output_dir),
            "--stem",
            stem,
        ],
        timeout=120,
    )
    path = output_dir / f"{stem}.json"
    diagnostic = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"passed": diagnostic.get("passed") is True, "diagnostic": diagnostic, "exit_code": proc.returncode}


def run_run_window_readiness(live_ver_dir: Path, target_generation: int) -> dict[str, Any]:
    from doofus.reports.run_window_telemetry_filter import filter_events_by_run_window, read_jsonl

    proc_path = live_ver_dir / "live_cycle_process_result.json"
    if not proc_path.exists():
        return {"passed": False, "reason": "missing live_cycle_process_result.json"}
    proc = json.loads(proc_path.read_text(encoding="utf-8"))
    start_dt = datetime.fromisoformat(proc["start"])
    end_dt = datetime.fromisoformat(proc["end"])
    init_events = read_jsonl(WORKSPACE / "runtime" / "state" / "cycle_init_events.jsonl")
    source_gen = target_generation - 1
    filtered = filter_events_by_run_window(
        init_events,
        generation=source_gen,
        window_start=start_dt,
        window_end=end_dt,
        source_name="cycle_init_events.jsonl",
    )
    empty = filter_events_by_run_window(
        init_events,
        generation=target_generation,
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        source_name="cycle_init_events.jsonl",
    )
    return {
        "passed": filtered.run_window_filter_applied and empty.run_window_filter_applied,
        "source_window_start": proc.get("start"),
        "source_window_end": proc.get("end"),
        "events_in_source_window": len(filtered.events_in_window),
        "events_excluded_outside_source_window": filtered.events_excluded_count,
        "target_generation_empty_window_excluded": empty.events_excluded_count,
    }


def run_inline_rescue_rehearsal(script: str, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    proc = run_cmd([sys.executable, script, "--output-dir", str(output_dir)], timeout=120)
    path = output_dir / "POSTLIVE_NONLIVE_CERTIFICATION_REHEARSAL.json"
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"passed": payload.get("passed") is True, "rehearsal": payload, "exit_code": proc.returncode}


def validate_controlled_cycle_policy(policy_path: Path) -> dict[str, Any]:
    policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
    rules = policy.get("rules") or []
    checks = {
        "one_human_gate": policy.get("one_human_gate") is True,
        "no_auto_launch": "Doofus may not launch the next generation automatically." in rules,
        "stop_flag_blocks_loop": "Continuous loops remain blocked by stop flag." in rules,
        "live_execution_automation_false": policy.get("live_execution_automation") is False,
    }
    return {"passed": all(checks.values()), "checks": checks, "policy_path": str(policy_path)}


def live_launch_env() -> dict[str, str]:
    from doofus.model_router.openrouter_live_config import apply_openrouter_live_env

    env = os.environ.copy()
    for key in ("DOOFUS_STATE", "DOOFUS_METRICS_DB", "DOOFUS_CONTROL", "DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS"):
        env.pop(key, None)
    env.pop("DOOFUS_FORCE_MODEL_DRY_RUN", None)
    return apply_openrouter_live_env(env)


def run_live_one_cycle(*, operator_approved: bool) -> dict[str, Any]:
    if not operator_approved:
        return {"passed": False, "reason": "operator_approved_one_cycle required"}
    cmd = [
        sys.executable,
        "-m",
        "doofus.supervisor.provider_aware_live_cycle",
        "--operator-approved-one-cycle",
        "--max-model-calls",
        "2",
        "--max-cost-usd",
        "0.05",
    ]
    start = datetime.now().astimezone().isoformat()
    proc = run_cmd(cmd, env=live_launch_env(), timeout=7200)
    end = datetime.now().astimezone().isoformat()
    try:
        cycle_out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        cycle_out = {"raw_stdout": (proc.stdout or "")[-3000:], "parse_error": True}
    return {
        "start": start,
        "end": end,
        "exit_code": proc.returncode,
        "command": " ".join(cmd),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "cycle_output": cycle_out,
    }
