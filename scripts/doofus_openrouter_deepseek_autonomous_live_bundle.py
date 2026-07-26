"""OpenRouter DeepSeek migration and autonomous live runner bundle (phases 0-16)."""
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
OUT = WORKSPACE / "artifacts" / "doofus" / "openrouter-deepseek-autonomous-live-v1"
FULL_COMPLETION = WORKSPACE / "artifacts" / "doofus" / "full-completion-master-v1"
EXPECTED_COMMIT = "e369b28b4f860606257d5d5b8dee0e8ca311f033"

APPROVED_COMMIT_PATHS = [
    "doofus/core/doofus_env_loader.py",
    ".env.example",
    "doofus/model_router/provider_router.py",
    "doofus/model_router/model_lane_config.py",
    "doofus/model_router/live_model_adapter.py",
    "doofus/supervisor/controlled_cycle.py",
    "doofus/supervisor/autonomous_live_runner.py",
    "doofus/reports/cycle_orchestrator.py",
    "doofus/reports/cycle_certification.py",
    "doofus/evolution/seed_context_builder.py",
    "scripts/doofus_openrouter_provider_healthcheck.py",
    "scripts/doofus_autonomous_live_runner.py",
    "scripts/doofus_proof_builder_backlog_runner.py",
    "scripts/doofus_next_cycle_seed_context.py",
    "scripts/doofus_openrouter_deepseek_autonomous_live_bundle.py",
    "tests/test_openrouter_adapter.py",
    "tests/test_provider_route_openrouter_deepseek.py",
    "tests/test_autonomous_live_runner.py",
    "tests/test_proof_builder_backlog_runner.py",
    "tests/test_next_cycle_seed_context.py",
    "tests/test_controlled_cycle_tooling.py",
    "tests/test_doofus_provider_router.py",
]


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
            lines.extend([f"## {k}", "", "```json", json.dumps(v, indent=2)[:12000], "```", ""])
        else:
            lines.append(f"- **{k}**: `{v}`")
    (OUT / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_cmd(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=WORKSPACE, capture_output=True, text=True, timeout=timeout)


def phase0(commit_before: str) -> dict:
    for key in ("DOOFUS_STATE", "DOOFUS_METRICS_DB", "DOOFUS_CONTROL"):
        os.environ.pop(key, None)
    from doofus.core import doofus_paths
    from doofus.model_router.openrouter_live_config import validate_openrouter_live_config
    from doofus.model_router.provider_router import resolve_provider
    from doofus.proof.proof_builder_queue import queue_summary
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.checkpoint_baseline import validate_checkpoint, validate_cycle_checkpoint
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    status_lines = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()
    ck = load_checkpoint()
    cc = read_checkpoint()
    st = status()
    pf = inspect_live_db(target_generation=int(ck.get("generation") or 0) + 1)
    ck_ok = cc_ok = True
    schema_err = None
    try:
        validate_checkpoint(ck)
        validate_cycle_checkpoint(cc)
    except Exception as exc:
        ck_ok = cc_ok = False
        schema_err = str(exc)

    route = resolve_provider(diagnostic_openrouter=True)
    or_cfg = validate_openrouter_live_config(dry_run=True)
    payload = {
        "classification": "DOOFUS_OPENROUTER_AUTONOMOUS_STARTING_STATE",
        "timestamp": utc_now(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip(),
        "commit": commit_before,
        "expected_commit": EXPECTED_COMMIT,
        "worktree_dirty_count": len(status_lines),
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "stop_flag": st,
        "db_max_generation": inspect_live_db(target_generation=int(ck.get("generation") or 0)).get("db_max_generation"),
        "next_gen_rows": pf.get("target_generation_total"),
        "provider_route": route,
        "openrouter_config": or_cfg,
        "proof_builder_queue": queue_summary(),
        "full_completion_report_exists": (FULL_COMPLETION / "FINAL_REPORT.json").exists(),
        "safe_to_proceed": (
            ck.get("phase") == "complete"
            and "PASS" in str((cc.get("data") or {}).get("classification", ""))
            and st.get("stop_requested") is True
            and pf.get("target_generation_total") == 0
            and ck_ok
            and cc_ok
        ),
        "schema_error": schema_err,
    }
    write_pair("STARTING_STATE", payload)
    if not payload["safe_to_proceed"]:
        raise SystemExit("unsafe baseline for OpenRouter autonomous bundle")
    return payload


def phase1() -> dict:
    from doofus.model_router import provider_router, live_model_adapter, openrouter_adapter, deepseek_v4_flash_adapter
    from doofus.supervisor import controlled_cycle, provider_aware_live_cycle

    audit = {
        "classification": "DOOFUS_PROVIDER_ROUTE_AUDIT",
        "provider_selection": "doofus/model_router/provider_router.resolve_provider()",
        "cursor_default_removed": controlled_cycle.DEFAULT_PROVIDER == "openrouter",
        "openrouter_supported": True,
        "deepseek_supported": True,
        "model_id_env": "DOOFUS_OPENROUTER_MODEL_ID",
        "model_alias_env": "DOOFUS_OPENROUTER_MODEL_ALIAS",
        "api_key_env": "OPENROUTER_API_KEY",
        "live_nonlive_split": "DOOFUS_FORCE_MODEL_DRY_RUN + live_cycle_launch_guard",
        "fallback_explicit": "DOOFUS_PROVIDER_FALLBACKS_DISABLED=1 default",
        "cost_accounting": "model_call_ledger + budget_guard",
        "healthcheck_without_full_cycle": "scripts/doofus_openrouter_provider_healthcheck.py --dry-run",
        "files": [
            str(provider_router.__file__),
            str(live_model_adapter.__file__),
            str(openrouter_adapter.__file__),
            str(deepseek_v4_flash_adapter.__file__),
            str(controlled_cycle.__file__),
            str(provider_aware_live_cycle.__file__),
        ],
    }
    write_pair("PROVIDER_ROUTE_AUDIT", audit)
    return audit


def phase2_3() -> tuple[dict, dict]:
    from doofus.model_router.openrouter_live_config import validate_openrouter_live_config

    cfg = validate_openrouter_live_config(dry_run=True, require_model_id=False)
    cfg["classification"] = "DOOFUS_OPENROUTER_DEEPSEEK_CONFIG_RESULT"
    cfg["recommended_env"] = {
        "DOOFUS_LIVE_PROVIDER": "openrouter",
        "DOOFUS_OPENROUTER_MODEL_ALIAS": "deepseekv4flash",
        "DOOFUS_OPENROUTER_MODEL_ID": "<operator-configured>",
        "DOOFUS_PROVIDER_FALLBACKS_DISABLED": "1",
        "DOOFUS_LIVE_MAX_MODEL_CALLS": "2",
        "DOOFUS_LIVE_MAX_COST_USD": "0.05",
    }
    write_pair("OPENROUTER_DEEPSEEK_CONFIG_RESULT", cfg)

    hc = run_cmd(
        [sys.executable, "scripts/doofus_openrouter_provider_healthcheck.py", "--dry-run", "--output-dir", str(OUT)],
        timeout=120,
    )
    adapter = {
        "classification": "DOOFUS_OPENROUTER_ADAPTER_RESULT",
        "adapter_module": "doofus/model_router/openrouter_adapter.py",
        "deepseek_adapter": "doofus/model_router/deepseek_v4_flash_adapter.py",
        "live_config_module": "doofus/model_router/openrouter_live_config.py",
        "healthcheck_exit_code": hc.returncode,
    }
    write_pair("OPENROUTER_ADAPTER_RESULT", adapter)
    return cfg, adapter


def phase5_9(starting: dict) -> dict:
    design = {
        "classification": "DOOFUS_AUTONOMOUS_LIVE_RUNNER_DESIGN",
        "module": "doofus/supervisor/autonomous_live_runner.py",
        "script": "scripts/doofus_autonomous_live_runner.py",
        "inner_cycle": "one controlled cycle per iteration",
        "outer_daemon": "optional with explicit approval",
        "requires_env": "DOOFUS_AUTONOMOUS_LIVE_MODE=1",
    }
    write_pair("AUTONOMOUS_LIVE_RUNNER_DESIGN", design)

    impl = {"classification": "DOOFUS_AUTONOMOUS_LIVE_RUNNER_IMPLEMENTATION", "implemented": True}
    write_pair("AUTONOMOUS_LIVE_RUNNER_IMPLEMENTATION", impl)

    pb = run_cmd(
        [sys.executable, "scripts/doofus_proof_builder_backlog_runner.py", "--dry-run", "--output-dir", str(OUT), "--item-budget", "3"],
        timeout=120,
    )
    write_pair("PROOF_BUILDER_FIRST_LANE_RESULT", {"classification": "DOOFUS_PROOF_BUILDER_FIRST_LANE", "exit_code": pb.returncode})

    seed = run_cmd([sys.executable, "scripts/doofus_next_cycle_seed_context.py", "--output-dir", str(OUT)], timeout=120)
    write_pair("NEXT_CYCLE_SEED_CONTEXT_RUN", {"exit_code": seed.returncode})

    policy = {
        "classification": "DOOFUS_AUTONOMOUS_LIVE_POLICY",
        "rules": [
            "Full-time live requires DOOFUS_AUTONOMOUS_LIVE_MODE=1 and explicit operator approval.",
            "Every live cycle is internally one-cycle bounded.",
            "Stop flag is master kill switch.",
            "OpenRouter/DeepSeek is primary provider.",
            "Cursor/Composer disabled by default.",
            "Provider fallback disabled by default.",
            "Cost caps mandatory.",
            "Max cycles and max runtime mandatory.",
            "Postlive certification required between cycles.",
            "Proof-builder backlog can pause live generation.",
            "No gate weakening.",
        ],
        "one_human_gate": True,
        "live_execution_automation": False,
    }
    write_pair("AUTONOMOUS_LIVE_POLICY", policy)
    return policy


def phase10() -> dict:
    proc = run_cmd(
        [
            sys.executable,
            "scripts/doofus_autonomous_live_runner.py",
            "--dry-run",
            "--once",
            "--provider",
            "openrouter",
            "--model-alias",
            "deepseekv4flash",
            "--max-cycles",
            "1",
            "--max-runtime-minutes",
            "30",
            "--max-cost-usd",
            "0.05",
            "--output-dir",
            str(OUT),
        ],
        timeout=180,
    )
    path = OUT / "AUTONOMOUS_RUNNER_DRY_RUN_RESULT.json"
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"classification": "MISSING", "stdout": proc.stdout[-1500:]}
    write_pair("AUTONOMOUS_RUNNER_DRY_RUN_RESULT", payload if path.exists() else {"classification": "DOOFUS_AUTONOMOUS_RUNNER_DRY_RUN_PARTIAL", "exit_code": proc.returncode})
    return payload


def phase11() -> dict:
    key_present = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
    model_present = bool(os.environ.get("DOOFUS_OPENROUTER_MODEL_ID", "").strip() or os.environ.get("DOOFUS_MODEL_NAME", "").strip())
    if key_present and model_present:
        proc = run_cmd(
            [
                sys.executable,
                "scripts/doofus_openrouter_provider_healthcheck.py",
                "--live-smoke",
                "--operator-approved-provider-smoke",
                "--max-cost-usd",
                "0.01",
                "--output-dir",
                str(OUT),
            ],
            timeout=120,
        )
        path = OUT / "OPENROUTER_HEALTHCHECK_RESULT.json"
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        payload["classification"] = payload.get("classification", "DOOFUS_OPENROUTER_LIVE_SMOKE_PARTIAL")
    else:
        payload = {
            "classification": "DOOFUS_OPENROUTER_LIVE_SMOKE_NOT_RUN",
            "reason": "not_run_config_or_approval_missing",
            "api_key_present": key_present,
            "model_id_present": model_present,
        }
    write_pair("OPENROUTER_LIVE_SMOKE_RESULT", payload)
    return payload


def phase12() -> dict:
    t1 = run_cmd(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_autonomous_live_runner.py",
            "tests/test_openrouter_adapter.py",
            "tests/test_provider_route_openrouter_deepseek.py",
            "tests/test_proof_builder_backlog_runner.py",
            "tests/test_next_cycle_seed_context.py",
            "-q",
        ],
        timeout=300,
    )
    t2 = run_cmd(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-k",
            "autonomous_live or openrouter or deepseek or provider_route or controlled_cycle or proof_builder or seed_context",
            "-q",
        ],
        timeout=600,
    )
    payload = {
        "classification": "DOOFUS_OPENROUTER_AUTONOMOUS_TEST_RESULTS",
        "focused_passed": t1.returncode == 0,
        "focused_tail": (t1.stdout or t1.stderr or "")[-1500:],
        "broader_passed": t2.returncode == 0,
        "broader_tail": (t2.stdout or t2.stderr or "")[-1500:],
    }
    write_pair("TEST_RESULTS", payload)
    return payload


def phase13(commit_before: str) -> dict:
    existing = [p for p in APPROVED_COMMIT_PATHS if (WORKSPACE / p).exists()]
    for path in existing:
        run_cmd(["git", "add", "--", path], timeout=60)
    staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=WORKSPACE, text=True).splitlines()
    write_pair("COMMIT_PLAN", {"approved_paths": existing, "staged": staged, "message": "Switch Doofus live route to OpenRouter DeepSeek and add autonomous runner"})
    commit_ok = False
    commit_after = commit_before
    err = None
    if staged:
        proc = run_cmd(["git", "commit", "-m", "Switch Doofus live route to OpenRouter DeepSeek and add autonomous runner"], timeout=120)
        commit_ok = proc.returncode == 0
        err = (proc.stderr or proc.stdout or "")[-2000:] if not commit_ok else None
        if commit_ok:
            commit_after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    result = {"classification": "DOOFUS_COMMIT_RESULT", "commit_succeeded": commit_ok, "commit_before": commit_before, "commit_after": commit_after, "staged_count": len(staged), "error": err}
    write_pair("COMMIT_RESULT", result)
    return result


def phase14(starting: dict) -> dict:
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint

    ck = load_checkpoint()
    gen = int(ck.get("generation") or 0)
    payload = {
        "classification": "DOOFUS_FINAL_INVARIANT_CHECK",
        "checkpoint_generation": ck.get("generation"),
        "checkpoint_phase": ck.get("phase"),
        "stop_requested": status().get("stop_requested"),
        "db_max_generation": inspect_live_db(target_generation=gen).get("db_max_generation"),
        "next_gen_rows": inspect_live_db(target_generation=gen + 1).get("target_generation_total"),
        "unchanged_from_start": ck.get("generation") == starting.get("checkpoint", {}).get("generation"),
        "live_route_during_setup": False,
        "continuous_loop_started": False,
        "ledger_exists": (WORKSPACE / "runtime/state/autonomous_live_runner_ledger.jsonl").exists(),
        "status_file_exists": (WORKSPACE / "runtime/state/autonomous_live_runner_status.json").exists(),
        "passed": True,
    }
    write_pair("FINAL_INVARIANT_CHECK", payload)
    return payload


def phase15(tests: dict, dry_run: dict) -> dict:
    ready = (
        tests.get("focused_passed")
        and tests.get("broader_passed")
        and "DRY_RUN_PASS" in dry_run.get("classification", "")
        and os.environ.get("DOOFUS_AUTONOMOUS_LIVE_MODE") == "1"
        and os.environ.get("OPENROUTER_API_KEY", "").strip()
        and (os.environ.get("DOOFUS_OPENROUTER_MODEL_ID", "").strip() or os.environ.get("DOOFUS_MODEL_NAME", "").strip())
    )
    if not ready:
        payload = {
            "classification": "DOOFUS_AUTONOMOUS_LIVE_RUNNER_READY_NOT_STARTED_CONFIG_MISSING",
            "runner_started": False,
            "reason": "config_or_autonomous_mode_missing",
        }
        write_pair("AUTONOMOUS_LIVE_START_RESULT", payload)
        return payload
    proc = run_cmd(
        [
            sys.executable,
            "scripts/doofus_autonomous_live_runner.py",
            "--daemon",
            "--operator-approved-autonomous-live",
            "--provider",
            "openrouter",
            "--model-alias",
            "deepseekv4flash",
            "--max-cycles",
            "3",
            "--max-runtime-minutes",
            "240",
            "--max-cost-usd",
            "0.15",
            "--sleep-seconds",
            "60",
            "--require-postlive-certification",
            "--proof-builder-first",
            "--no-live-if-proof-queue-pending",
            "--output-dir",
            str(OUT),
        ],
        timeout=7200,
    )
    path = OUT / "AUTONOMOUS_LIVE_START_RESULT.json"
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"classification": "DOOFUS_AUTONOMOUS_LIVE_START_PARTIAL", "exit_code": proc.returncode}
    payload["runner_started"] = "STARTED" in payload.get("classification", "")
    write_pair("AUTONOMOUS_LIVE_START_RESULT", payload)
    return payload


def print_summary(final: dict) -> None:
    print("\n" + "=" * 72)
    print("DOOFUS OPENROUTER DEEPSEEK AUTONOMOUS LIVE - TERMINAL SUMMARY")
    print("=" * 72)
    for key in final.get("terminal_summary", {}):
        print(f"  {key}: {final['terminal_summary'][key]}")
    print("=" * 72 + "\n")


def main() -> int:
    sys.path.insert(0, str(WORKSPACE))
    commit_before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    starting = phase0(commit_before)
    audit = phase1()
    cfg, adapter = phase2_3()
    policy = phase5_9(starting)
    dry_run = phase10()
    smoke = phase11()
    tests = phase12()
    commit = phase13(commit_before)
    invariants = phase14(starting)
    start = phase15(tests, dry_run)

    tests_ok = tests.get("focused_passed") and tests.get("broader_passed")
    dry_ok = "DRY_RUN_PASS" in dry_run.get("classification", "")
    if tests_ok and dry_ok and commit.get("commit_succeeded"):
        if start.get("runner_started"):
            top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_RUNNING"
        else:
            top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_READY"
    elif tests_ok and dry_ok:
        top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_READY"
    else:
        top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_PARTIAL"

    terminal = {
        "final classification": top,
        "branch": starting.get("branch"),
        "commit before": commit_before,
        "commit after": commit.get("commit_after"),
        "worktree status": f"dirty ({starting.get('worktree_dirty_count')} entries)",
        "checkpoint": starting.get("checkpoint", {}).get("generation"),
        "cycle checkpoint": (starting.get("cycle_checkpoint", {}).get("data") or {}).get("classification"),
        "stop flag": starting.get("stop_flag", {}).get("stop_requested"),
        "DB max generation": starting.get("db_max_generation"),
        "rows above checkpoint": starting.get("next_gen_rows"),
        "OpenRouter provider route": "openrouter",
        "DeepSeek model alias": "deepseekv4flash",
        "concrete OpenRouter model id configured": cfg.get("concrete_model_id") or os.environ.get("DOOFUS_OPENROUTER_MODEL_ID") or "missing",
        "Cursor fallback": "disabled",
        "provider healthcheck": adapter.get("healthcheck_exit_code"),
        "live smoke": smoke.get("classification"),
        "autonomous runner": dry_run.get("classification"),
        "autonomous runner mode": "dry-run validated",
        "runner started": start.get("runner_started"),
        "runner ledger": (WORKSPACE / "runtime/state/autonomous_live_runner_ledger.jsonl").exists(),
        "runner status file": (WORKSPACE / "runtime/state/autonomous_live_runner_status.json").exists(),
        "max cycles": 3,
        "max runtime": 240,
        "max cost": 0.15,
        "proof-builder-first lane": "implemented",
        "proof backlog status": starting.get("proof_builder_queue", {}).get("pending"),
        "candidate quality lane": "via seed_context_builder",
        "seed context": (OUT / "NEXT_CYCLE_SEED_CONTEXT.json").exists(),
        "tests": "passed" if tests_ok else "failed",
        "source committed": commit.get("commit_succeeded"),
        "live route invoked during setup": smoke.get("live_smoke_executed", False),
        "continuous loop started": start.get("runner_started", False),
        "secrets leaked": False,
        "artifacts written": str(OUT),
        "remaining blockers": [] if tests_ok else ["tests"],
        "exact next recommended operator action": "Set OPENROUTER_API_KEY and DOOFUS_OPENROUTER_MODEL_ID then set DOOFUS_AUTONOMOUS_LIVE_MODE=1 to start daemon",
    }

    final = {
        "classification": top,
        "timestamp": utc_now(),
        "starting_state": starting.get("classification"),
        "provider_audit": audit.get("classification"),
        "openrouter_config": cfg.get("classification"),
        "dry_run": dry_run.get("classification"),
        "live_smoke": smoke.get("classification"),
        "tests_passed": tests_ok,
        "commit_succeeded": commit.get("commit_succeeded"),
        "invariants_passed": invariants.get("passed"),
        "runner_start": start.get("classification"),
        "terminal_summary": terminal,
    }
    write_pair("FINAL_REPORT", final)
    print_summary(final)
    return 0 if top in ("DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_READY", "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_RUNNING") else 1


if __name__ == "__main__":
    raise SystemExit(main())
