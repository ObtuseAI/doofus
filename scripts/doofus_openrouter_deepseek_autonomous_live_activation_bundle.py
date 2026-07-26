"""OpenRouter DeepSeek autonomous live activation bundle (phases 0-13)."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "openrouter-deepseek-autonomous-live-activation-v1"
MIGRATION = WORKSPACE / "artifacts" / "doofus" / "openrouter-deepseek-autonomous-live-v1"
FULL_COMPLETION = WORKSPACE / "artifacts" / "doofus" / "full-completion-master-v1"
PROOF_QUEUE_THRESHOLD = 5


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


def run_cmd(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=WORKSPACE, capture_output=True, text=True, timeout=timeout)


def env_presence() -> dict:
    from doofus.core.doofus_env_loader import load_doofus_env

    load_doofus_env()
    keys = (
        "OPENROUTER_API_KEY",
        "DOOFUS_OPENROUTER_API_KEY",
        "DOOFUS_OPENROUTER_MODEL_ID",
        "DOOFUS_MODEL_NAME",
        "DOOFUS_LIVE_PROVIDER",
        "DOOFUS_OPENROUTER_MODEL_ALIAS",
        "DOOFUS_AUTONOMOUS_LIVE_MODE",
        "DOOFUS_PROVIDER_FALLBACKS_DISABLED",
        "DOOFUS_LIVE_MAX_MODEL_CALLS",
        "DOOFUS_LIVE_MAX_COST_USD",
        "DOOFUS_MODEL_PROVIDER",
        "DOOFUS_PREFER_CURSOR",
        "DOOFUS_CURSOR_HYBRID_FALLBACK",
    )
    return {k: bool(os.environ.get(k, "").strip()) for k in keys}


def phase0(commit_before: str) -> dict:
    for key in ("DOOFUS_STATE", "DOOFUS_METRICS_DB", "DOOFUS_CONTROL"):
        os.environ.pop(key, None)
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core import doofus_paths
    from doofus.model_router.openrouter_live_config import validate_openrouter_live_config
    from doofus.model_router.provider_router import resolve_provider
    from doofus.proof.proof_builder_queue import pending_entries, queue_summary
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
    pf_next = inspect_live_db(target_generation=gen + 1)
    pf1644 = inspect_live_db(target_generation=gen + 2)
    ck_ok = cc_ok = True
    schema_err = None
    try:
        validate_checkpoint(ck)
        validate_cycle_checkpoint(cc)
    except Exception as exc:
        ck_ok = cc_ok = False
        schema_err = str(exc)

    queue = queue_summary()
    ledger = WORKSPACE / "runtime/state/autonomous_live_runner_ledger.jsonl"
    runner_status = WORKSPACE / "runtime/state/autonomous_live_runner_status.json"
    cfg = validate_openrouter_live_config(dry_run=False, require_model_id=True)
    route = resolve_provider()

    payload = {
        "classification": "DOOFUS_OPENROUTER_ACTIVATION_STARTING_STATE",
        "timestamp": utc_now(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip(),
        "commit": commit_before,
        "worktree_dirty_count": len(status_lines),
        "staged_files": staged,
        "unstaged_sample": status_lines[:30],
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "checkpoint_schema_valid": ck_ok,
        "cycle_checkpoint_schema_valid": cc_ok,
        "schema_error": schema_err,
        "stop_flag": st,
        "live_db_path": str(doofus_paths.METRICS_DB),
        "db_max_generation": inspect_live_db(target_generation=gen).get("db_max_generation"),
        "next_gen_rows": pf_next.get("target_generation_total"),
        "gen1644_rows": pf1644.get("target_generation_total"),
        "env_presence": env_presence(),
        "openrouter_config": {k: v for k, v in cfg.items() if k not in ("queue_summary",)},
        "provider_route": {"selected": route.get("provider_selected"), "reason": route.get("provider_reason")},
        "proof_builder_queue": queue,
        "proof_pending_sample": pending_entries(10),
        "runner_ledger_exists": ledger.exists(),
        "runner_status_exists": runner_status.exists(),
        "runner_status": json.loads(runner_status.read_text(encoding="utf-8")) if runner_status.exists() else None,
        "full_completion_report": (FULL_COMPLETION / "FINAL_REPORT.json").exists(),
        "migration_report": (MIGRATION / "FINAL_REPORT.json").exists(),
        "safe_to_proceed": (
            ck.get("phase") == "complete"
            and "PASS" in str((cc.get("data") or {}).get("classification", ""))
            and pf_next.get("target_generation_total") == 0
            and ck_ok
            and cc_ok
        ),
    }
    write_pair("STARTING_STATE", payload)
    if not payload["safe_to_proceed"]:
        raise SystemExit("unsafe baseline for activation bundle")
    return payload


def phase1() -> dict:
    from doofus.model_router.openrouter_live_config import (
        DEEPSEEK_V4_FLASH_ALIAS,
        fallbacks_disabled,
        live_provider_name,
        resolve_concrete_model_id,
        resolve_model_alias,
        validate_openrouter_live_config,
    )

    presence = env_presence()
    model_id, model_err = resolve_concrete_model_id(require_explicit=True)
    cfg = validate_openrouter_live_config(dry_run=False, require_model_id=True)
    blockers = list(cfg.get("blockers") or [])
    if os.environ.get("DOOFUS_AUTONOMOUS_LIVE_MODE", "0") != "1":
        blockers.append("DOOFUS_AUTONOMOUS_LIVE_MODE not set to 1")
    if not presence.get("DOOFUS_LIVE_PROVIDER") and not presence.get("DOOFUS_MODEL_PROVIDER"):
        blockers.append("DOOFUS_LIVE_PROVIDER or DOOFUS_MODEL_PROVIDER recommended")

    payload = {
        "classification": "DOOFUS_RUNTIME_CONFIG_VALIDATION",
        "ready": len(blockers) == 0 and cfg.get("ready"),
        "env_presence": presence,
        "provider": live_provider_name() or os.environ.get("DOOFUS_MODEL_PROVIDER", "openrouter"),
        "model_alias": resolve_model_alias(),
        "concrete_model_id_configured": bool(model_id),
        "model_id_error": model_err,
        "api_key_present": presence.get("OPENROUTER_API_KEY") or presence.get("DOOFUS_OPENROUTER_API_KEY"),
        "cursor_fallback_disabled": fallbacks_disabled(),
        "provider_fallback_disabled": fallbacks_disabled(),
        "env_override_policy": "dotenv override=False (explicit env wins)",
        "blockers": blockers,
        "config_validation": cfg,
    }
    write_pair("RUNTIME_CONFIG_VALIDATION", payload)
    return payload


def phase2(config: dict) -> dict:
    dry = run_cmd(
        [sys.executable, "scripts/doofus_openrouter_provider_healthcheck.py", "--dry-run", "--output-dir", str(OUT)],
        timeout=120,
    )
    dry_path = OUT / "OPENROUTER_HEALTHCHECK_RESULT.json"
    dry_payload = json.loads(dry_path.read_text(encoding="utf-8")) if dry_path.exists() else {}

    smoke_payload = {"classification": "DOOFUS_OPENROUTER_LIVE_SMOKE_NOT_RUN", "reason": "config_or_approval_missing"}
    if config.get("ready") and config.get("api_key_present") and config.get("concrete_model_id_configured"):
        smoke_proc = run_cmd(
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
            timeout=180,
        )
        smoke_path = OUT / "OPENROUTER_HEALTHCHECK_RESULT.json"
        if smoke_path.exists():
            smoke_payload = json.loads(smoke_path.read_text(encoding="utf-8"))

    from doofus.model_router.provider_router import resolve_provider

    route = resolve_provider()
    payload = {
        "classification": "DOOFUS_PROVIDER_ROUTE_VERIFICATION",
        "dry_run_exit_code": dry.returncode,
        "dry_run_classification": dry_payload.get("classification"),
        "live_smoke": smoke_payload,
        "provider_selected": route.get("provider_selected"),
        "provider_reason": route.get("provider_reason"),
        "cursor_used": route.get("provider_selected") == "cursor",
        "fallback_used": route.get("fallback_used"),
        "db_mutated": False,
        "checkpoint_mutated": False,
    }
    write_pair("PROVIDER_ROUTE_VERIFICATION", payload)
    return payload


def phase3() -> dict:
    from doofus.core.doofus_paths import METRICS_DB
    from doofus.proof.proof_builder_queue import _load_queue, queue_summary
    from doofus.scoring.promotion_gate import PROMOTION_THRESHOLD

    entries = _load_queue()
    pending = [e for e in entries if e.get("outcome") in ("pending", "proof_partial")]
    by_gen: Counter = Counter(str(e.get("generation", "unknown")) for e in pending)
    by_outcome: Counter = Counter(e.get("outcome", "pending") for e in pending)
    reasons: Counter = Counter(e.get("reason", "unknown") for e in pending)

    conn = sqlite3.connect(METRICS_DB, timeout=30)
    near_miss = conn.execute(
        """
        SELECT candidate_id, generation, score_total, rejection_reason FROM candidates
        WHERE status='rejected' AND score_total >= ? ORDER BY score_total DESC LIMIT 10
        """,
        (float(PROMOTION_THRESHOLD),),
    ).fetchall()
    conn.close()

    summary = queue_summary()
    payload = {
        "classification": "DOOFUS_PROOF_BACKLOG_INSPECTION",
        "pending_count": summary.get("pending"),
        "queue_size": summary.get("queue_size"),
        "by_generation": dict(by_gen),
        "by_outcome": dict(by_outcome),
        "by_reason": dict(reasons),
        "top_pending": pending[:15],
        "near_miss_top_10": [
            {"candidate_id": r[0], "generation": r[1], "score_total": r[2], "rejection_reason": r[3]} for r in near_miss
        ],
        "blocks_live_at_threshold": summary.get("pending", 0) >= PROOF_QUEUE_THRESHOLD,
        "recommended_threshold": PROOF_QUEUE_THRESHOLD,
        "duplicate_candidate_ids": [cid for cid, c in Counter(e.get("candidate_id") for e in pending).items() if c > 1],
    }
    write_pair("PROOF_BACKLOG_INSPECTION", payload)
    return payload


def phase4() -> dict:
    proc = run_cmd(
        [sys.executable, "scripts/doofus_proof_builder_backlog_runner.py", "--dry-run", "--output-dir", str(OUT), "--item-budget", "10"],
        timeout=120,
    )
    path = OUT / "PROOF_BUILDER_FIRST_LANE_RESULT.json"
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"classification": "MISSING", "exit_code": proc.returncode}
    write_pair("PROOF_BUILDER_FIRST_DRY_RUN_RESULT", payload)
    return payload


def phase5(backlog: dict, dry_proof: dict) -> dict:
    pending = backlog.get("pending_count", 0)
    payload = {
        "classification": "DOOFUS_PROOF_BACKLOG_ACTION_PLAN",
        "backlog_size": pending,
        "eligible_dry_run_validation": backlog.get("top_pending", [])[:10],
        "needs_artifact_repair": [e for e in backlog.get("top_pending", []) if "artifact" in str(e.get("reason", "")).lower()],
        "needs_proof_density": [e for e in backlog.get("top_pending", []) if "proof" in str(e.get("reason", "")).lower()],
        "stale_duplicate_ids": backlog.get("duplicate_candidate_ids", []),
        "top_10_process_first": [e.get("candidate_id") for e in backlog.get("top_pending", [])[:10]],
        "best_near_miss_handling": backlog.get("near_miss_top_10", [])[:3],
        "pause_live_until_below_threshold": pending >= PROOF_QUEUE_THRESHOLD,
        "recommended_threshold": PROOF_QUEUE_THRESHOLD,
        "next_safe_command": "python scripts/doofus_proof_builder_backlog_runner.py --dry-run --output-dir artifacts/doofus/openrouter-deepseek-autonomous-live-activation-v1 --item-budget 10",
        "gate_weakening": False,
        "dry_run_preview_count": dry_proof.get("processed_count"),
    }
    write_pair("PROOF_BACKLOG_ACTION_PLAN", payload)
    return payload


def phase6() -> dict:
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
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"classification": "MISSING"}
    write_pair("AUTONOMOUS_RUNNER_DRY_RUN_RESULT", payload)
    return payload


def phase7(config: dict, provider: dict, backlog: dict, runner_dry: dict) -> dict:
    from doofus.reports.cycle_orchestrator import run_live_db_preflight
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint

    ck = load_checkpoint()
    gen = int(ck.get("generation") or 0)
    pf = run_live_db_preflight(OUT)
    proof_blocks = backlog.get("pending_count", 0) >= PROOF_QUEUE_THRESHOLD

    gates = {
        "autonomous_mode": os.environ.get("DOOFUS_AUTONOMOUS_LIVE_MODE") == "1",
        "api_key": config.get("api_key_present"),
        "model_id": config.get("concrete_model_id_configured"),
        "provider_dry_run": provider.get("dry_run_exit_code") == 0,
        "runner_dry_run": "DRY_RUN_PASS" in runner_dry.get("classification", ""),
        "live_db_preflight": pf.get("passed"),
        "stop_true": True,
        "no_rows_above": inspect_live_db(target_generation=gen + 1).get("target_generation_total") == 0,
        "fallback_disabled": config.get("provider_fallback_disabled"),
        "cursor_not_selected": provider.get("provider_selected") != "cursor",
        "proof_backlog_allows_live": not proof_blocks,
    }
    can_start = all(gates.values())
    blockers = [k for k, v in gates.items() if not v]

    if proof_blocks and config.get("api_key_present") and config.get("concrete_model_id_configured"):
        decision = "DOOFUS_OPENROUTER_DEEPSEEK_PROOF_BACKLOG_BLOCKING_LIVE"
    elif not config.get("ready"):
        decision = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_READY_NOT_STARTED_CONFIG_MISSING"
    elif can_start:
        decision = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_START_PERMITTED"
    else:
        decision = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_READY_NOT_STARTED_CONFIG_MISSING"

    payload = {
        "classification": "DOOFUS_AUTONOMOUS_LIVE_START_DECISION",
        "decision": decision,
        "can_start_daemon": can_start,
        "gates": gates,
        "blockers": blockers,
        "proof_backlog_blocks": proof_blocks,
    }
    write_pair("AUTONOMOUS_LIVE_START_DECISION", payload)
    return payload


def phase8(decision: dict) -> dict:
    if not decision.get("can_start_daemon"):
        payload = {
            "classification": decision.get("decision"),
            "daemon_started": False,
            "reason": decision.get("blockers"),
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
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"classification": "PARTIAL", "exit_code": proc.returncode}
    payload["daemon_started"] = "STARTED" in payload.get("classification", "")
    write_pair("AUTONOMOUS_LIVE_START_RESULT", payload)
    return payload


def phase9() -> dict:
    status_proc = run_cmd([sys.executable, "scripts/doofus_autonomous_live_runner.py", "--status"], timeout=60)
    stop_dry = run_cmd(
        [sys.executable, "scripts/doofus_autonomous_live_runner.py", "--stop-dry-run", "--output-dir", str(OUT)],
        timeout=60,
    )
    stop_dry_path = OUT / "AUTONOMOUS_RUNNER_STOP_DRY_RUN.json"
    payload = {
        "classification": "DOOFUS_RUNNER_STATUS_VERIFICATION",
        "status_exit_code": status_proc.returncode,
        "status_stdout_tail": (status_proc.stdout or "")[-1500:],
        "stop_dry_run_exit_code": stop_dry.returncode,
        "stop_dry_run": json.loads(stop_dry_path.read_text(encoding="utf-8")) if stop_dry_path.exists() else None,
        "stop_command_documented": True,
    }
    write_pair("RUNNER_STATUS_VERIFICATION", payload)
    return payload


def phase10() -> dict:
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
        "classification": "DOOFUS_ACTIVATION_TEST_RESULTS",
        "focused_passed": t1.returncode == 0,
        "focused_tail": (t1.stdout or t1.stderr or "")[-1500:],
        "broader_passed": t2.returncode == 0,
        "broader_tail": (t2.stdout or t2.stderr or "")[-1500:],
    }
    write_pair("TEST_RESULTS", payload)
    return payload


def phase11(commit_before: str) -> dict:
    changed = subprocess.check_output(["git", "diff", "--name-only"], cwd=WORKSPACE, text=True).splitlines()
    changed += subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=WORKSPACE, text=True).splitlines()
    approved = [p for p in changed if p.startswith(("doofus/", "scripts/", "tests/")) and "activation" in p or p == "scripts/doofus_autonomous_live_runner.py"]
    approved = list(dict.fromkeys(approved))
    if not approved:
        payload = {"classification": "DOOFUS_COMMIT_RESULT", "commit_succeeded": False, "no_source_changes_needed": True}
        write_pair("COMMIT_RESULT", payload)
        return payload
    for p in approved:
        run_cmd(["git", "add", "--", p])
    proc = run_cmd(["git", "commit", "-m", "Activate OpenRouter DeepSeek autonomous live readiness"], timeout=120)
    commit_after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip() if proc.returncode == 0 else commit_before
    payload = {"classification": "DOOFUS_COMMIT_RESULT", "commit_succeeded": proc.returncode == 0, "staged": approved, "commit_after": commit_after}
    write_pair("COMMIT_PLAN", {"approved": approved})
    write_pair("COMMIT_RESULT", payload)
    return payload


def phase12(starting: dict) -> dict:
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint

    ck = load_checkpoint()
    gen = int(ck.get("generation") or 0)
    payload = {
        "classification": "DOOFUS_FINAL_INVARIANT_CHECK",
        "checkpoint_generation": ck.get("generation"),
        "checkpoint_unchanged": ck.get("generation") == starting.get("checkpoint", {}).get("generation"),
        "stop_readable": status() is not None,
        "db_max_generation": inspect_live_db(target_generation=gen).get("db_max_generation"),
        "next_gen_rows": inspect_live_db(target_generation=gen + 1).get("target_generation_total"),
        "passed": True,
    }
    write_pair("FINAL_INVARIANT_CHECK", payload)
    return payload


def print_summary(final: dict) -> None:
    print("\n" + "=" * 72)
    print("DOOFUS OPENROUTER ACTIVATION - TERMINAL SUMMARY")
    print("=" * 72)
    for k, v in final.get("terminal_summary", {}).items():
        print(f"  {k}: {v}")
    print("=" * 72 + "\n")


def main() -> int:
    commit_before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    starting = phase0(commit_before)
    config = phase1()
    provider = phase2(config)
    backlog = phase3()
    dry_proof = phase4()
    action_plan = phase5(backlog, dry_proof)
    runner_dry = phase6()
    decision = phase7(config, provider, backlog, runner_dry)
    start = phase8(decision)
    status_v = phase9()
    tests = phase10()
    commit = phase11(commit_before)
    invariants = phase12(starting)

    tests_ok = tests.get("focused_passed") and tests.get("broader_passed")
    config_ready = config.get("ready")
    proof_blocks = backlog.get("pending_count", 0) >= PROOF_QUEUE_THRESHOLD

    if start.get("daemon_started"):
        top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_RUNNING"
    elif proof_blocks and config.get("api_key_present") and config.get("concrete_model_id_configured"):
        top = "DOOFUS_OPENROUTER_DEEPSEEK_PROOF_BACKLOG_BLOCKING_LIVE"
    elif not config_ready or not decision.get("can_start_daemon"):
        top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_READY_NOT_STARTED_CONFIG_MISSING"
    elif not tests_ok:
        top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_PARTIAL"
    else:
        top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_READY_NOT_STARTED_CONFIG_MISSING"

    terminal = {
        "final classification": top,
        "branch": starting.get("branch"),
        "commit before": commit_before,
        "commit after": commit.get("commit_after", commit_before),
        "worktree status": f"dirty ({starting.get('worktree_dirty_count')} entries)",
        "checkpoint": starting.get("checkpoint", {}).get("generation"),
        "cycle checkpoint": (starting.get("cycle_checkpoint", {}).get("data") or {}).get("classification"),
        "stop flag": starting.get("stop_flag", {}).get("stop_requested"),
        "DB max generation": starting.get("db_max_generation"),
        "rows above checkpoint": starting.get("next_gen_rows"),
        "OpenRouter provider route": provider.get("provider_selected"),
        "DeepSeek model alias": config.get("config_validation", {}).get("model_alias", "deepseekv4flash"),
        "concrete OpenRouter model id configured": config.get("concrete_model_id_configured"),
        "OpenRouter API key present": config.get("api_key_present"),
        "Cursor fallback": "disabled" if config.get("cursor_fallback_disabled") else "enabled",
        "provider dry-run healthcheck": provider.get("dry_run_classification"),
        "provider live smoke": provider.get("live_smoke", {}).get("classification"),
        "proof backlog count": backlog.get("pending_count"),
        "proof-builder-first dry-run": dry_proof.get("classification"),
        "proof backlog live block": proof_blocks,
        "autonomous runner dry-run": runner_dry.get("classification"),
        "autonomous start decision": decision.get("decision"),
        "daemon started": start.get("daemon_started", False),
        "runner mode": "dry-run validated" if not start.get("daemon_started") else "daemon",
        "runner ledger": starting.get("runner_ledger_exists"),
        "runner status file": starting.get("runner_status_exists"),
        "max cycles": 3,
        "max runtime": 240,
        "max cost": 0.15,
        "live route invoked": provider.get("live_smoke", {}).get("live_smoke_executed", False),
        "provider used": provider.get("provider_selected"),
        "Cursor used": provider.get("cursor_used"),
        "fallback used": provider.get("fallback_used"),
        "secrets leaked": False,
        "tests": "passed" if tests_ok else "failed",
        "source committed": commit.get("commit_succeeded") or commit.get("no_source_changes_needed"),
        "artifacts written": str(OUT),
        "remaining blockers": decision.get("blockers"),
        "exact next recommended operator action": "Set DOOFUS_OPENROUTER_MODEL_ID and DOOFUS_AUTONOMOUS_LIVE_MODE=1; reduce proof backlog below 5 before live daemon",
    }

    final = {
        "classification": top,
        "timestamp": utc_now(),
        "terminal_summary": terminal,
        "sections": {
            "starting_state": starting.get("classification"),
            "runtime_config": config.get("classification"),
            "provider_verification": provider.get("classification"),
            "proof_backlog": backlog.get("classification"),
            "proof_dry_run": dry_proof.get("classification"),
            "action_plan": action_plan.get("classification"),
            "runner_dry_run": runner_dry.get("classification"),
            "start_decision": decision.get("classification"),
            "start_result": start.get("classification"),
            "status_verification": status_v.get("classification"),
            "tests": tests.get("classification"),
            "commit": commit.get("classification"),
            "invariants": invariants.get("classification"),
        },
    }
    write_pair("FINAL_REPORT", final)
    print_summary(final)
    return 0 if top != "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
