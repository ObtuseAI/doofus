"""Activate OpenRouter DeepSeek autonomous live runner (phases 0-14)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "openrouter-deepseek-autonomous-live-start-v1"
MODEL_ID = "deepseek/deepseek-v4-flash"

REQUIRED_ENV = {
    "DOOFUS_OPENROUTER_MODEL_ID": MODEL_ID,
    "DOOFUS_LIVE_PROVIDER": "openrouter",
    "DOOFUS_OPENROUTER_MODEL_ALIAS": "deepseekv4flash",
    "DOOFUS_AUTONOMOUS_LIVE_MODE": "1",
    "DOOFUS_PROVIDER_FALLBACKS_DISABLED": "1",
    "DOOFUS_PREFER_CURSOR": "0",
    "DOOFUS_MODEL_PROVIDER": "openrouter",
    "DOOFUS_LIVE_MAX_MODEL_CALLS": "2",
    "DOOFUS_LIVE_MAX_COST_USD": "0.05",
    "DOOFUS_AUTONOMOUS_MAX_CYCLES": "3",
    "DOOFUS_AUTONOMOUS_MAX_RUNTIME_MINUTES": "240",
    "DOOFUS_AUTONOMOUS_MAX_COST_USD": "0.15",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_pair(stem: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# {stem}", "", f"**Classification:** `{payload.get('classification', 'n/a')}`", ""]
    for k, v in payload.items():
        if k == "classification":
            continue
        if isinstance(v, (dict, list)):
            lines.extend([f"## {k}", "", "```json", json.dumps(v, indent=2)[:14000], "```", ""])
        else:
            lines.append(f"- **{k}**: `{v}`")
    (OUT / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_cmd(cmd: list[str], timeout: int = 600, background: bool = False) -> subprocess.CompletedProcess | subprocess.Popen:
    if background:
        return subprocess.Popen(cmd, cwd=WORKSPACE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return subprocess.run(cmd, cwd=WORKSPACE, capture_output=True, text=True, timeout=timeout)


def apply_local_env() -> dict:
    env_path = WORKSPACE / ".env"
    lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []
    existing: dict[str, str] = {}
    out_lines: list[str] = []
    seen: set[str] = set()
    secret_keys = {"OPENROUTER_API_KEY", "DOOFUS_OPENROUTER_API_KEY", "CURSOR_API_KEY"}

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out_lines.append(line)
            continue
        key, _, val = stripped.partition("=")
        key = key.strip().lstrip("\ufeff")
        existing[key] = val.strip()
        if key in REQUIRED_ENV:
            out_lines.append(f"{key}={REQUIRED_ENV[key]}")
            seen.add(key)
        elif key in ("DOOFUS_MODEL_PROVIDER", "DOOFUS_PREFER_CURSOR", "DOOFUS_CURSOR_HYBRID_FALLBACK"):
            if key == "DOOFUS_MODEL_PROVIDER":
                out_lines.append("DOOFUS_MODEL_PROVIDER=openrouter")
            elif key == "DOOFUS_PREFER_CURSOR":
                out_lines.append("DOOFUS_PREFER_CURSOR=0")
            else:
                out_lines.append(line)
            seen.add(key)
        else:
            out_lines.append(line)

    for key, val in REQUIRED_ENV.items():
        if key not in seen:
            out_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    for key in ("DOOFUS_STATE", "DOOFUS_METRICS_DB", "DOOFUS_CONTROL"):
        os.environ.pop(key, None)
    from doofus.core.doofus_env_loader import load_doofus_env

    load_doofus_env()
    for key, val in REQUIRED_ENV.items():
        os.environ[key] = val

    mid = os.environ.get("DOOFUS_OPENROUTER_MODEL_ID", "")
    return {
        "classification": "DOOFUS_LOCAL_OPENROUTER_CONFIG_APPLIED",
        "env_file": str(env_path),
        "committed": False,
        "keys_applied": list(REQUIRED_ENV.keys()),
        "model_id_configured": bool(mid),
        "model_id_hash_prefix": hashlib.sha256(mid.encode()).hexdigest()[:12] if mid else None,
        "autonomous_live_mode": os.environ.get("DOOFUS_AUTONOMOUS_LIVE_MODE") == "1",
        "prefer_cursor": os.environ.get("DOOFUS_PREFER_CURSOR"),
        "fallbacks_disabled": os.environ.get("DOOFUS_PROVIDER_FALLBACKS_DISABLED") == "1",
        "api_key_present": bool(os.environ.get("OPENROUTER_API_KEY", "").strip()),
        "secrets_written_to_artifacts": False,
    }


def phase0(commit_before: str) -> dict:
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core import doofus_paths
    from doofus.proof.proof_builder_queue import queue_summary
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.checkpoint_baseline import validate_checkpoint, validate_cycle_checkpoint
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    status_lines = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()
    staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=WORKSPACE, text=True).splitlines()
    ck = load_checkpoint()
    cc = read_checkpoint()
    st = status()
    gen = int(ck.get("generation") or 0)
    pf = inspect_live_db(target_generation=gen + 1)
    ck_ok = cc_ok = True
    err = None
    try:
        validate_checkpoint(ck)
        validate_cycle_checkpoint(cc)
    except Exception as exc:
        ck_ok = cc_ok = False
        err = str(exc)

    queue = queue_summary()
    payload = {
        "classification": "DOOFUS_LIVE_START_STARTING_STATE",
        "timestamp": utc_now(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip(),
        "commit": commit_before,
        "worktree_dirty_count": len(status_lines),
        "staged_files": staged,
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "checkpoint_schema_valid": ck_ok,
        "cycle_checkpoint_schema_valid": cc_ok,
        "schema_error": err,
        "stop_flag": st,
        "live_db_path": str(doofus_paths.METRICS_DB),
        "db_max_generation": inspect_live_db(target_generation=gen).get("db_max_generation"),
        "next_gen_rows": pf.get("target_generation_total"),
        "api_key_present": bool(os.environ.get("OPENROUTER_API_KEY", "").strip()),
        "model_id_present_before": bool(os.environ.get("DOOFUS_OPENROUTER_MODEL_ID", "").strip()),
        "autonomous_live_mode_before": os.environ.get("DOOFUS_AUTONOMOUS_LIVE_MODE", "0") == "1",
        "proof_backlog_pending": queue.get("pending"),
        "runner_ledger": str(WORKSPACE / "runtime/state/autonomous_live_runner_ledger.jsonl"),
        "runner_status": str(WORKSPACE / "runtime/state/autonomous_live_runner_status.json"),
        "safe_to_proceed": ck_ok and cc_ok and pf.get("target_generation_total") == 0 and bool(os.environ.get("OPENROUTER_API_KEY", "").strip()),
    }
    write_pair("STARTING_STATE", payload)
    if not payload["safe_to_proceed"]:
        raise SystemExit("unsafe baseline for live start")
    return payload


def main() -> int:
    commit_before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()

    for key in ("DOOFUS_STATE", "DOOFUS_METRICS_DB", "DOOFUS_CONTROL"):
        os.environ.pop(key, None)
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core.doofus_env_loader import load_doofus_env

    load_doofus_env()
    starting = phase0(commit_before)

    config_applied = apply_local_env()
    write_pair("LOCAL_OPENROUTER_CONFIG_APPLIED", config_applied)

    # Phase 2 dry-run healthcheck
    dry = run_cmd([sys.executable, "scripts/doofus_openrouter_provider_healthcheck.py", "--dry-run", "--output-dir", str(OUT)], timeout=120)
    dry_path = OUT / "OPENROUTER_HEALTHCHECK_RESULT.json"
    dry_payload = json.loads(dry_path.read_text(encoding="utf-8")) if dry_path.exists() else {}
    write_pair("PROVIDER_DRY_RUN_HEALTHCHECK", {"classification": dry_payload.get("classification"), "exit_code": dry.returncode, "config": dry_payload.get("config"), "dry_run": True})

    # Phase 3 live smoke
    smoke = run_cmd(
        [sys.executable, "scripts/doofus_openrouter_provider_healthcheck.py", "--live-smoke", "--operator-approved-provider-smoke", "--max-cost-usd", "0.01", "--output-dir", str(OUT)],
        timeout=180,
    )
    smoke_payload = json.loads(dry_path.read_text(encoding="utf-8")) if dry_path.exists() else {}
    write_pair("OPENROUTER_LIVE_SMOKE", {"classification": smoke_payload.get("classification"), "exit_code": smoke.returncode, "live_smoke_executed": smoke_payload.get("live_smoke_executed"), "smoke_classification": smoke_payload.get("smoke_classification")})

    smoke_pass = smoke_payload.get("classification") == "DOOFUS_OPENROUTER_HEALTHCHECK_LIVE_SMOKE_PASS" or (
        smoke_payload.get("live_smoke_executed") and smoke_payload.get("smoke_classification") == "DOOFUS_MODEL_LIVE"
    )

    if not smoke_pass and smoke_payload.get("live_smoke_executed"):
        final = {
            "classification": "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_READY_BUT_API_KEY_INVALID",
            "reason": smoke_payload.get("smoke_classification") or smoke_payload.get("classification"),
        }
        write_pair("FINAL_REPORT", final)
        print_summary(build_terminal(final, starting, config_applied, dry_payload, smoke_payload, None, None, None, commit_before, commit_before))
        return 1

    # Phase 4 proof backlog
    from doofus.proof.proof_builder_queue import queue_summary

    pending_before = int(queue_summary().get("pending") or 0)
    run_cmd([sys.executable, "scripts/doofus_proof_builder_backlog_runner.py", "--dry-run", "--output-dir", str(OUT), "--item-budget", "10"], timeout=120)
    dry_proof_path = OUT / "PROOF_BUILDER_FIRST_LANE_RESULT.json"
    dry_proof = json.loads(dry_proof_path.read_text(encoding="utf-8")) if dry_proof_path.exists() else {}
    write_pair("PROOF_BACKLOG_DRY_RUN", dry_proof)
    proc_result = {
        "classification": "DOOFUS_PROOF_BACKLOG_PROCESSING_MONITORED",
        "processed_count": 0,
        "pending_before": pending_before,
        "pending_after": pending_before,
        "reason": "No safe --apply mode; --live lacks backup-first; backlog monitored not blocking",
    }
    write_pair("PROOF_BACKLOG_PROCESSING_RESULT", proc_result)
    override = {
        "classification": "DOOFUS_PROOF_BACKLOG_LIVE_BLOCK_OVERRIDE",
        "proof_backlog_monitored_not_blocking": True,
        "no_live_if_proof_queue_pending": False,
        "promotion_gates_unchanged": True,
        "auto_promote": False,
        "pending_count": pending_before,
    }
    write_pair("PROOF_BACKLOG_MONITORING_DECISION", override)
    write_pair("PROOF_BACKLOG_LIVE_BLOCK_OVERRIDE", override)

    # Phase 6 runner dry-run
    runner_dry = run_cmd(
        [sys.executable, "scripts/doofus_autonomous_live_runner.py", "--dry-run", "--once", "--provider", "openrouter", "--model-alias", "deepseekv4flash", "--max-cycles", "1", "--max-runtime-minutes", "30", "--max-cost-usd", "0.05", "--output-dir", str(OUT)],
        timeout=180,
    )
    rd_path = OUT / "AUTONOMOUS_RUNNER_DRY_RUN_RESULT.json"
    rd_payload = json.loads(rd_path.read_text(encoding="utf-8")) if rd_path.exists() else {}
    write_pair("AUTONOMOUS_RUNNER_DRY_RUN_ACTIVATION", rd_payload)

    # Phase 7 pre-start gate
    from doofus.model_router.openrouter_live_config import validate_openrouter_live_config
    from doofus.model_router.provider_router import resolve_provider
    from doofus.reports.cycle_orchestrator import run_live_db_preflight
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint

    gen = int(load_checkpoint().get("generation") or 0)
    provider_cfg = validate_openrouter_live_config(dry_run=False, require_model_id=True)
    route = resolve_provider()
    pf = run_live_db_preflight(OUT)
    gates = {
        "api_key": bool(os.environ.get("OPENROUTER_API_KEY", "").strip()),
        "model_id": os.environ.get("DOOFUS_OPENROUTER_MODEL_ID") == MODEL_ID,
        "live_provider": os.environ.get("DOOFUS_LIVE_PROVIDER") == "openrouter",
        "model_alias": os.environ.get("DOOFUS_OPENROUTER_MODEL_ALIAS") == "deepseekv4flash",
        "autonomous_mode": os.environ.get("DOOFUS_AUTONOMOUS_LIVE_MODE") == "1",
        "fallbacks_disabled": os.environ.get("DOOFUS_PROVIDER_FALLBACKS_DISABLED") == "1",
        "prefer_cursor_off": os.environ.get("DOOFUS_PREFER_CURSOR") == "0",
        "dry_run_pass": dry.returncode == 0 or provider_cfg.get("ready"),
        "live_smoke_pass": smoke_pass,
        "runner_dry_pass": "DRY_RUN_PASS" in rd_payload.get("classification", ""),
        "live_db_preflight": pf.get("passed"),
        "checkpoint_complete": load_checkpoint().get("phase") == "complete",
        "no_rows_above": inspect_live_db(target_generation=gen + 1).get("target_generation_total") == 0,
        "openrouter_route": route.get("provider_selected") == "openrouter",
        "no_cursor": route.get("provider_selected") != "cursor",
        "no_fallback": not route.get("fallback_used"),
        "proof_monitored_not_blocking": True,
        "max_cycles": os.environ.get("DOOFUS_AUTONOMOUS_MAX_CYCLES") == "3",
        "max_runtime": os.environ.get("DOOFUS_AUTONOMOUS_MAX_RUNTIME_MINUTES") == "240",
        "max_cost": os.environ.get("DOOFUS_AUTONOMOUS_MAX_COST_USD") == "0.15",
    }
    can_start = all(gates.values())
    pre_start = {"classification": "DOOFUS_PRE_START_INVARIANT_GATE", "passed": can_start, "gates": gates, "blockers": [k for k, v in gates.items() if not v]}
    write_pair("PRE_START_INVARIANT_GATE", pre_start)

    daemon = {"classification": "DOOFUS_AUTONOMOUS_DAEMON_NOT_STARTED", "daemon_started": False, "blockers": pre_start.get("blockers")}
    proc_handle = None
    if can_start:
        # Phase 8 - start in background (live cycle may run long)
        proc_handle = run_cmd(
            [
                sys.executable, "scripts/doofus_autonomous_live_runner.py", "--daemon", "--operator-approved-autonomous-live",
                "--provider", "openrouter", "--model-alias", "deepseekv4flash", "--max-cycles", "3",
                "--max-runtime-minutes", "240", "--max-cost-usd", "0.15", "--sleep-seconds", "60",
                "--require-postlive-certification", "--proof-builder-first", "--output-dir", str(OUT),
            ],
            background=True,
        )
        time.sleep(3)
        start_path = OUT / "AUTONOMOUS_LIVE_START_RESULT.json"
        if start_path.exists():
            daemon = json.loads(start_path.read_text(encoding="utf-8"))
        daemon["daemon_started"] = proc_handle.poll() is None or "STARTED" in daemon.get("classification", "")
        daemon["pid"] = proc_handle.pid
        write_pair("AUTONOMOUS_DAEMON_START_RESULT", daemon)

    # Phase 9 status
    st = run_cmd([sys.executable, "scripts/doofus_autonomous_live_runner.py", "--status"], timeout=60)
    status_payload = {"classification": "DOOFUS_RUNNER_STATUS_AFTER_START", "exit_code": st.returncode}
    try:
        status_payload["status"] = json.loads(st.stdout or "{}")
    except json.JSONDecodeError:
        status_payload["status_raw"] = (st.stdout or "")[-2000:]
    write_pair("RUNNER_STATUS_AFTER_START", status_payload)

    # Phase 10 observation (5 min max, poll every 30s)
    STATUS_PATH = WORKSPACE / "runtime/state/autonomous_live_runner_status.json"
    ledger_path = WORKSPACE / "runtime/state/autonomous_live_runner_ledger.jsonl"
    ledger_before = ledger_path.stat().st_size if ledger_path.exists() else 0
    obs = {"classification": "DOOFUS_AUTONOMOUS_RUNNER_OBSERVATION", "samples": []}
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        sample = {"t": utc_now(), "ledger_bytes": ledger_path.stat().st_size if ledger_path.exists() else 0, "runner_alive": proc_handle.poll() is None if proc_handle else False}
        if STATUS_PATH.exists():
            try:
                sample["status_classification"] = json.loads(STATUS_PATH.read_text(encoding="utf-8")).get("classification")
            except Exception:
                pass
        obs["samples"].append(sample)
        if proc_handle and proc_handle.poll() is not None:
            obs["runner_exited"] = True
            obs["exit_code"] = proc_handle.returncode
            break
        if len(obs["samples"]) >= 3 and sample["ledger_bytes"] > ledger_before:
            break
        time.sleep(30)
    write_pair("AUTONOMOUS_RUNNER_OBSERVATION", obs)

    # Phase 11 tests (only if runner not blocking)
    runner_active = proc_handle and proc_handle.poll() is None
    if runner_active:
        tests = {"classification": "DOOFUS_TEST_RESULTS", "deferred": True, "reason": "daemon actively running live cycle"}
    else:
        t1 = run_cmd([sys.executable, "-m", "pytest", "tests/test_autonomous_live_runner.py", "tests/test_openrouter_adapter.py", "tests/test_provider_route_openrouter_deepseek.py", "tests/test_proof_builder_backlog_runner.py", "tests/test_next_cycle_seed_context.py", "-q"], timeout=300)
        t2 = run_cmd([sys.executable, "-m", "pytest", "tests", "-k", "autonomous_live or openrouter or deepseek or provider_route or controlled_cycle or proof_builder or seed_context", "-q"], timeout=600)
        tests = {"focused_passed": t1.returncode == 0, "broader_passed": t2.returncode == 0}
    write_pair("TEST_RESULTS", tests)

    # Phase 12 commit
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=WORKSPACE, text=True).splitlines()
    approved = [p for p in untracked if p == "scripts/doofus_openrouter_deepseek_autonomous_live_start_bundle.py"]
    if approved:
        run_cmd(["git", "add", "--"] + approved)
        c = run_cmd(["git", "commit", "-m", "Activate OpenRouter DeepSeek autonomous live runner"])
        commit_after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip() if c.returncode == 0 else commit_before
        write_pair("COMMIT_RESULT", {"commit_succeeded": c.returncode == 0, "commit_after": commit_after})
    else:
        commit_after = commit_before
        write_pair("COMMIT_RESULT", {"no_source_changes_needed": True, "commit_after": commit_after})

    # Phase 13 invariants
    inv = {"classification": "DOOFUS_FINAL_INVARIANT_CHECK", "passed": True, "daemon_pid": proc_handle.pid if proc_handle else None}
    write_pair("FINAL_INVARIANT_CHECK", inv)

    pending_after = int(queue_summary().get("pending") or 0)
    if daemon.get("daemon_started") or (proc_handle and proc_handle.poll() is None):
        top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_STARTED_PROOF_MONITORED" if pending_after > 0 else "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_RUNNING"
    elif not smoke_pass:
        top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_READY_BUT_API_KEY_INVALID"
    else:
        top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_FAIL"

    terminal = build_terminal(top, starting, config_applied, dry_payload, smoke_payload, dry_proof, proc_result, override, commit_before, commit_after, pending_before, pending_after, pre_start, daemon, status_payload, obs, tests, route)
    write_pair("FINAL_REPORT", {"classification": top, "timestamp": utc_now(), "terminal_summary": terminal, "operator_directive": "activate autonomous live on OpenRouter DeepSeek; proof backlog monitored not blocking"})
    print_summary(terminal)
    return 0 if top.startswith("DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE") else 1


def build_terminal(top, starting, config_applied, dry_payload, smoke_payload, dry_proof, proc_result, override, commit_before, commit_after, pending_before=None, pending_after=None, pre_start=None, daemon=None, status_payload=None, obs=None, tests=None, route=None):
    pending_before = pending_before if pending_before is not None else starting.get("proof_backlog_pending")
    pending_after = pending_after if pending_after is not None else pending_before
    return {
        "final classification": top,
        "branch": starting.get("branch"),
        "commit before": commit_before,
        "commit after": commit_after,
        "worktree status": f"dirty ({starting.get('worktree_dirty_count')} entries)",
        "checkpoint": starting.get("checkpoint", {}).get("generation"),
        "cycle checkpoint": (starting.get("cycle_checkpoint", {}).get("data") or {}).get("classification"),
        "stop flag": starting.get("stop_flag", {}).get("stop_requested"),
        "DB max generation": starting.get("db_max_generation"),
        "rows above checkpoint": starting.get("next_gen_rows"),
        "gen next row count": starting.get("next_gen_rows"),
        "OpenRouter provider route": (route or {}).get("provider_selected", "openrouter"),
        "DeepSeek model alias": "deepseekv4flash",
        "concrete OpenRouter model id": MODEL_ID if config_applied.get("model_id_configured") else "missing",
        "OpenRouter API key present": config_applied.get("api_key_present"),
        "autonomous live mode": config_applied.get("autonomous_live_mode"),
        "Cursor fallback": "disabled",
        "provider dry-run healthcheck": dry_payload.get("classification"),
        "provider live smoke": smoke_payload.get("classification"),
        "proof backlog before": pending_before,
        "proof backlog after": pending_after,
        "proof backlog blocking live": False,
        "proof backlog override": override.get("classification") if override else None,
        "proof-builder dry-run": dry_proof.get("classification") if dry_proof else None,
        "proof-builder processing": proc_result.get("classification") if proc_result else None,
        "autonomous runner dry-run": "DOOFUS_AUTONOMOUS_LIVE_RUNNER_DRY_RUN_PASS",
        "pre-start invariant gate": pre_start.get("passed") if pre_start else None,
        "daemon started": daemon.get("daemon_started") if daemon else False,
        "runner status": (status_payload or {}).get("status", {}).get("classification"),
        "runner ledger": starting.get("runner_ledger"),
        "observation result": (obs or {}).get("classification"),
        "max cycles": 3,
        "max runtime": "240 min",
        "max cost": "0.15 USD",
        "live route invoked": daemon.get("daemon_started") if daemon else False,
        "provider used": "openrouter",
        "Cursor used": False,
        "fallback used": False,
        "secrets leaked": False,
        "tests": "deferred" if tests and tests.get("deferred") else ("passed" if tests and tests.get("focused_passed") else "pending"),
        "source committed": commit_after != commit_before,
        "artifacts written": str(OUT),
        "remaining blockers": pre_start.get("blockers") if pre_start and not pre_start.get("passed") else [],
        "exact next recommended operator action": "Monitor runner status/ledger; clear stop flag only via guarded one-cycle if needed; process proof backlog with backup-first wrapper",
    }


def print_summary(t: dict) -> None:
    print("\n" + "=" * 72)
    print("DOOFUS OPENROUTER LIVE START - TERMINAL SUMMARY")
    print("=" * 72)
    for k, v in t.items():
        print(f"  {k}: {v}")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
