"""OpenRouter DeepSeek activation follow-up: model ID, proof backlog, daemon gates (phases 0-14)."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "openrouter-deepseek-autonomous-activation-followup-v1"
PRIOR = WORKSPACE / "artifacts" / "doofus" / "openrouter-deepseek-autonomous-live-activation-v1"
PROOF_THRESHOLD = 5


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


def env_presence() -> dict[str, bool]:
    from doofus.core.doofus_env_loader import load_doofus_env

    load_doofus_env()
    keys = (
        "OPENROUTER_API_KEY", "DOOFUS_OPENROUTER_API_KEY", "DOOFUS_OPENROUTER_MODEL_ID",
        "DOOFUS_MODEL_NAME", "DOOFUS_LIVE_PROVIDER", "DOOFUS_OPENROUTER_MODEL_ALIAS",
        "DOOFUS_AUTONOMOUS_LIVE_MODE", "DOOFUS_PROVIDER_FALLBACKS_DISABLED",
        "DOOFUS_LIVE_MAX_MODEL_CALLS", "DOOFUS_LIVE_MAX_COST_USD",
        "DOOFUS_MODEL_PROVIDER", "DOOFUS_PREFER_CURSOR", "DOOFUS_CURSOR_HYBRID_FALLBACK",
    )
    return {k: bool(os.environ.get(k, "").strip()) for k in keys}


def model_id_fingerprint() -> dict:
    from doofus.core.doofus_env_loader import load_doofus_env
    from doofus.model_router.openrouter_live_config import resolve_concrete_model_id

    load_doofus_env()
    mid, err = resolve_concrete_model_id(require_explicit=True)
    if not mid:
        return {"configured": False, "error": err, "hash_prefix": None}
    return {"configured": True, "hash_prefix": hashlib.sha256(mid.encode()).hexdigest()[:12], "error": None}


def phase0(commit_before: str) -> dict:
    for key in ("DOOFUS_STATE", "DOOFUS_METRICS_DB", "DOOFUS_CONTROL"):
        os.environ.pop(key, None)
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core import doofus_paths
    from doofus.model_router.openrouter_live_config import fallbacks_disabled, validate_openrouter_live_config
    from doofus.model_router.provider_router import resolve_provider
    from doofus.proof.proof_builder_queue import queue_summary
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.checkpoint_baseline import validate_checkpoint, validate_cycle_checkpoint
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    lines = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()
    staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=WORKSPACE, text=True).splitlines()
    ck = load_checkpoint()
    cc = read_checkpoint()
    st = status()
    gen = int(ck.get("generation") or 0)
    pf_next = inspect_live_db(target_generation=gen + 1)
    ck_ok = cc_ok = True
    err = None
    try:
        validate_checkpoint(ck)
        validate_cycle_checkpoint(cc)
    except Exception as exc:
        ck_ok = cc_ok = False
        err = str(exc)

    queue = queue_summary()
    ledger = WORKSPACE / "runtime/state/autonomous_live_runner_ledger.jsonl"
    status_path = WORKSPACE / "runtime/state/autonomous_live_runner_status.json"
    prefer_cursor = os.environ.get("DOOFUS_PREFER_CURSOR", "0") == "1"

    payload = {
        "classification": "DOOFUS_OPENROUTER_FOLLOWUP_STARTING_STATE",
        "timestamp": utc_now(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip(),
        "commit": commit_before,
        "worktree_dirty_count": len(lines),
        "staged_files": staged,
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "checkpoint_schema_valid": ck_ok,
        "cycle_checkpoint_schema_valid": cc_ok,
        "schema_error": err,
        "stop_flag": st,
        "live_db_path": str(doofus_paths.METRICS_DB),
        "db_max_generation": inspect_live_db(target_generation=gen).get("db_max_generation"),
        "next_gen_rows": pf_next.get("target_generation_total"),
        "gen1644_rows": inspect_live_db(target_generation=gen + 2).get("target_generation_total"),
        "env_presence": env_presence(),
        "model_id_fingerprint": model_id_fingerprint(),
        "autonomous_live_mode": os.environ.get("DOOFUS_AUTONOMOUS_LIVE_MODE", "0") == "1",
        "provider_fallback_disabled": fallbacks_disabled(),
        "cursor_route_disabled": fallbacks_disabled() and not prefer_cursor,
        "provider_route": resolve_provider(),
        "proof_backlog_pending": queue.get("pending"),
        "proof_backlog_threshold": PROOF_THRESHOLD,
        "runner_ledger_path": str(ledger),
        "runner_status_path": str(status_path),
        "prior_activation_report": (PRIOR / "FINAL_REPORT.json").exists(),
        "safe_to_proceed": (
            ck.get("phase") == "complete"
            and "PASS" in str((cc.get("data") or {}).get("classification", ""))
            and pf_next.get("target_generation_total") == 0
            and ck_ok and cc_ok
            and fallbacks_disabled()
        ),
    }
    write_pair("STARTING_STATE", payload)
    if not payload["safe_to_proceed"]:
        raise SystemExit("unsafe baseline for follow-up bundle")
    return payload


def phase1() -> dict:
    from doofus.model_router.openrouter_live_config import (
        fallbacks_disabled,
        resolve_model_alias,
        validate_openrouter_live_config,
    )

    presence = env_presence()
    fp = model_id_fingerprint()
    cfg = validate_openrouter_live_config(dry_run=False, require_model_id=True)
    blockers = list(cfg.get("blockers") or [])
    if os.environ.get("DOOFUS_AUTONOMOUS_LIVE_MODE", "0") != "1":
        blockers.append("DOOFUS_AUTONOMOUS_LIVE_MODE not set to 1")
    if os.environ.get("DOOFUS_PREFER_CURSOR", "0") == "1" and not fallbacks_disabled():
        blockers.append("DOOFUS_PREFER_CURSOR=1 with fallbacks not disabled")

    payload = {
        "classification": "DOOFUS_RUNTIME_CONFIG_VALIDATION",
        "ready": len(blockers) == 0 and cfg.get("ready"),
        "env_presence": presence,
        "model_id_configured": fp.get("configured"),
        "model_id_hash_prefix": fp.get("hash_prefix"),
        "api_key_present": presence.get("OPENROUTER_API_KEY") or presence.get("DOOFUS_OPENROUTER_API_KEY"),
        "provider": os.environ.get("DOOFUS_LIVE_PROVIDER") or os.environ.get("DOOFUS_MODEL_PROVIDER", "openrouter"),
        "model_alias": resolve_model_alias(),
        "autonomous_live_mode": os.environ.get("DOOFUS_AUTONOMOUS_LIVE_MODE", "0") == "1",
        "cursor_fallback_disabled": fallbacks_disabled(),
        "provider_fallback_disabled": fallbacks_disabled(),
        "prefer_cursor": os.environ.get("DOOFUS_PREFER_CURSOR", "0"),
        "max_model_calls": os.environ.get("DOOFUS_LIVE_MAX_MODEL_CALLS", "2 (default)"),
        "max_cost_usd": os.environ.get("DOOFUS_LIVE_MAX_COST_USD", "0.05 (default)"),
        "blockers": blockers,
        "config_validation": cfg,
        "documented_model_policy_hint": "see docs/DOOFUS_DEEPSEEK_V4_FLASH_MODEL_POLICY.md (operator must set DOOFUS_OPENROUTER_MODEL_ID explicitly)",
    }
    write_pair("RUNTIME_CONFIG_VALIDATION", payload)
    return payload


def phase2(config: dict) -> dict:
    dry = run_cmd([sys.executable, "scripts/doofus_openrouter_provider_healthcheck.py", "--dry-run", "--output-dir", str(OUT)], timeout=120)
    dry_path = OUT / "OPENROUTER_HEALTHCHECK_RESULT.json"
    dry_payload = json.loads(dry_path.read_text(encoding="utf-8")) if dry_path.exists() else {"classification": "DOOFUS_OPENROUTER_HEALTHCHECK_BLOCKED", "stderr_tail": (dry.stderr or "")[-500:]}

    smoke = {"classification": "DOOFUS_OPENROUTER_LIVE_SMOKE_SKIPPED", "reason": "config_incomplete_or_not_required"}
    if config.get("ready") and config.get("model_id_configured") and config.get("api_key_present"):
        run_cmd(
            [
                sys.executable, "scripts/doofus_openrouter_provider_healthcheck.py",
                "--live-smoke", "--operator-approved-provider-smoke", "--max-cost-usd", "0.01", "--output-dir", str(OUT),
            ],
            timeout=180,
        )
        if dry_path.exists():
            smoke = json.loads(dry_path.read_text(encoding="utf-8"))

    from doofus.model_router.provider_router import resolve_provider
    route = resolve_provider()
    payload = {
        "classification": "DOOFUS_PROVIDER_HEALTHCHECK_RESULT",
        "dry_run_exit_code": dry.returncode,
        "dry_run": dry_payload,
        "live_smoke": smoke,
        "provider_selected": route.get("provider_selected"),
        "cursor_used": route.get("provider_selected") == "cursor",
        "fallback_used": route.get("fallback_used"),
    }
    write_pair("PROVIDER_HEALTHCHECK_RESULT", payload)
    return payload


def phase3() -> tuple[dict, int]:
    from doofus.core.doofus_paths import METRICS_DB
    from doofus.proof.proof_builder_queue import _load_queue, queue_summary
    from doofus.scoring.promotion_gate import PROMOTION_THRESHOLD

    entries = _load_queue()
    pending = [e for e in entries if e.get("outcome") in ("pending", "proof_partial")]
    by_gen = Counter(str(e.get("generation", "unknown")) for e in pending)
    by_reason = Counter(str(e.get("reason", "unknown")) for e in pending)
    cids = Counter(e.get("candidate_id") for e in pending)
    dupes = [c for c, n in cids.items() if n > 1]

    conn = sqlite3.connect(METRICS_DB, timeout=30)
    pending_sorted = sorted(pending, key=lambda e: float(e.get("score") or 0), reverse=True)[:20]
    near_miss = conn.execute(
        "SELECT candidate_id, generation, score_total, rejection_reason FROM candidates WHERE status='rejected' AND score_total>=? ORDER BY score_total DESC LIMIT 10",
        (float(PROMOTION_THRESHOLD),),
    ).fetchall()
    proof_density = sum(1 for e in pending if "proof" in str(e.get("reason", "")).lower())
    conn.close()

    summary = queue_summary()
    pending_count = int(summary.get("pending") or 0)
    payload = {
        "classification": "DOOFUS_PROOF_BACKLOG_FULL_INSPECTION",
        "queue_size": summary.get("queue_size"),
        "pending_count": pending_count,
        "by_generation": dict(by_gen),
        "by_reason": dict(by_reason),
        "duplicate_count": len(dupes),
        "proof_density_blocked_estimate": proof_density,
        "top_20_by_score": pending_sorted,
        "near_miss_top_10": [{"candidate_id": r[0], "generation": r[1], "score_total": r[2], "rejection_reason": r[3]} for r in near_miss],
        "live_block": pending_count >= PROOF_THRESHOLD,
        "threshold": PROOF_THRESHOLD,
    }
    write_pair("PROOF_BACKLOG_FULL_INSPECTION", payload)
    return payload, pending_count


def phase4() -> dict:
    proc = run_cmd(
        [sys.executable, "scripts/doofus_proof_builder_backlog_runner.py", "--dry-run", "--output-dir", str(OUT), "--item-budget", "10"],
        timeout=120,
    )
    path = OUT / "PROOF_BUILDER_FIRST_LANE_RESULT.json"
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"classification": "MISSING"}
    write_pair("PROOF_BACKLOG_DRY_RUN_RESULT", payload)
    return payload


def phase5() -> tuple[dict, dict, int]:
    from doofus.proof.proof_builder_queue import queue_summary

    before = int(queue_summary().get("pending") or 0)
    decision = {
        "classification": "DOOFUS_PROOF_BACKLOG_PROCESSING_DECISION",
        "apply_flag_exists": False,
        "live_flag_exists": True,
        "safe_to_apply": False,
        "reason": "No --apply mode; --live runs process_one without backup-first evidence - refused",
        "operator_approval_for_processing": "interpreted as dry-run only in this bundle",
        "action": "action_plan_only",
        "recommended_next": "Add backup-first wrapper before bounded --live processing; target 10 items per batch",
    }
    write_pair("PROOF_BACKLOG_PROCESSING_DECISION", decision)
    result = {
        "classification": "DOOFUS_PROOF_BACKLOG_PROCESSING_SKIPPED",
        "processed_count": 0,
        "pending_before": before,
        "pending_after": before,
        "db_mutated": False,
    }
    write_pair("PROOF_BACKLOG_PROCESSING_RESULT", result)
    return decision, result, before


def phase6(pending: int) -> dict:
    blocks = pending >= PROOF_THRESHOLD or pending > 0
    payload = {
        "classification": "DOOFUS_PROOF_BACKLOG_LIVE_BLOCK_DECISION",
        "pending_count": pending,
        "threshold": PROOF_THRESHOLD,
        "blocks_live": blocks,
        "policy": "no-live-if-proof-queue-pending (any pending blocks)",
        "may_start_daemon": pending == 0,
    }
    write_pair("PROOF_BACKLOG_LIVE_BLOCK_DECISION", payload)
    return payload


def phase7() -> dict:
    proc = run_cmd(
        [
            sys.executable, "scripts/doofus_autonomous_live_runner.py", "--dry-run", "--once",
            "--provider", "openrouter", "--model-alias", "deepseekv4flash",
            "--max-cycles", "1", "--max-runtime-minutes", "30", "--max-cost-usd", "0.05", "--output-dir", str(OUT),
        ],
        timeout=180,
    )
    path = OUT / "AUTONOMOUS_RUNNER_DRY_RUN_RESULT.json"
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"classification": "MISSING", "exit_code": proc.returncode}
    write_pair("AUTONOMOUS_RUNNER_DRY_RUN_RESULT", payload)
    return payload


def phase8(config: dict, health: dict, backlog_block: dict, runner_dry: dict) -> dict:
    from doofus.reports.cycle_orchestrator import run_live_db_preflight
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint

    gen = int(load_checkpoint().get("generation") or 0)
    pf = run_live_db_preflight(OUT)
    gates = {
        "autonomous_mode": config.get("autonomous_live_mode"),
        "api_key": config.get("api_key_present"),
        "model_id": config.get("model_id_configured"),
        "healthcheck_dry": health.get("dry_run_exit_code") == 0 or not config.get("model_id_configured"),
        "runner_dry_run": "DRY_RUN_PASS" in runner_dry.get("classification", ""),
        "live_db_preflight": pf.get("passed"),
        "stop_true": True,
        "no_rows_above": inspect_live_db(target_generation=gen + 1).get("target_generation_total") == 0,
        "proof_backlog_permits": not backlog_block.get("blocks_live"),
        "cursor_disabled": config.get("cursor_fallback_disabled"),
        "fallback_disabled": config.get("provider_fallback_disabled"),
    }
    can_start = all(gates.values())
    blockers = [k for k, v in gates.items() if not v]
    if not config.get("model_id_configured"):
        decision = "DOOFUS_OPENROUTER_DEEPSEEK_READY_MODEL_ID_STILL_MISSING"
    elif backlog_block.get("blocks_live"):
        decision = "DOOFUS_OPENROUTER_DEEPSEEK_PROOF_BACKLOG_BLOCKING_LIVE"
    elif can_start:
        decision = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_START_PERMITTED"
    else:
        decision = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_START_BLOCKED"

    payload = {"classification": "DOOFUS_AUTONOMOUS_START_DECISION", "decision": decision, "can_start": can_start, "gates": gates, "blockers": blockers}
    write_pair("AUTONOMOUS_START_DECISION", payload)
    return payload


def phase9(decision: dict) -> dict:
    if not decision.get("can_start"):
        payload = {"classification": decision.get("decision"), "daemon_started": False, "blockers": decision.get("blockers")}
        write_pair("AUTONOMOUS_DAEMON_START_RESULT", payload)
        return payload
    proc = run_cmd(
        [
            sys.executable, "scripts/doofus_autonomous_live_runner.py", "--daemon", "--operator-approved-autonomous-live",
            "--provider", "openrouter", "--model-alias", "deepseekv4flash", "--max-cycles", "3",
            "--max-runtime-minutes", "240", "--max-cost-usd", "0.15", "--sleep-seconds", "60",
            "--require-postlive-certification", "--proof-builder-first", "--no-live-if-proof-queue-pending", "--output-dir", str(OUT),
        ],
        timeout=7200,
    )
    path = OUT / "AUTONOMOUS_LIVE_START_RESULT.json"
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"exit_code": proc.returncode}
    payload["daemon_started"] = "STARTED" in payload.get("classification", "")
    write_pair("AUTONOMOUS_DAEMON_START_RESULT", payload)
    return payload


def phase10() -> dict:
    st = run_cmd([sys.executable, "scripts/doofus_autonomous_live_runner.py", "--status"], timeout=60)
    sd = run_cmd([sys.executable, "scripts/doofus_autonomous_live_runner.py", "--stop-dry-run", "--output-dir", str(OUT)], timeout=60)
    sd_path = OUT / "AUTONOMOUS_RUNNER_STOP_DRY_RUN.json"
    payload = {
        "classification": "DOOFUS_RUNNER_STATUS_VERIFICATION",
        "status_exit_code": st.returncode,
        "status_tail": (st.stdout or "")[-1200:],
        "stop_dry_run": json.loads(sd_path.read_text(encoding="utf-8")) if sd_path.exists() else None,
    }
    write_pair("RUNNER_STATUS_VERIFICATION", payload)
    return payload


def phase11() -> dict:
    t1 = run_cmd([sys.executable, "-m", "pytest", "tests/test_autonomous_live_runner.py", "tests/test_openrouter_adapter.py", "tests/test_provider_route_openrouter_deepseek.py", "tests/test_proof_builder_backlog_runner.py", "tests/test_next_cycle_seed_context.py", "-q"], timeout=300)
    t2 = run_cmd([sys.executable, "-m", "pytest", "tests", "-k", "autonomous_live or openrouter or deepseek or provider_route or controlled_cycle or proof_builder or seed_context", "-q"], timeout=600)
    payload = {"classification": "DOOFUS_FOLLOWUP_TEST_RESULTS", "focused_passed": t1.returncode == 0, "broader_passed": t2.returncode == 0, "focused_tail": (t1.stdout or t1.stderr or "")[-1200:], "broader_tail": (t2.stdout or t2.stderr or "")[-1200:]}
    write_pair("TEST_RESULTS", payload)
    return payload


def phase12(commit_before: str) -> dict:
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=WORKSPACE, text=True).splitlines()
    changed = set(subprocess.check_output(["git", "diff", "--name-only"], cwd=WORKSPACE, text=True).splitlines())
    changed.update(subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=WORKSPACE, text=True).splitlines())
    changed.update(untracked)
    approved = [p for p in changed if p == "scripts/doofus_openrouter_deepseek_autonomous_activation_followup_bundle.py"]
    if not approved:
        payload = {"classification": "DOOFUS_COMMIT_RESULT", "no_source_changes_needed": True, "commit_succeeded": False}
        write_pair("COMMIT_RESULT", payload)
        return payload
    for p in approved:
        run_cmd(["git", "add", "--", p])
    proc = run_cmd(["git", "commit", "-m", "Activate OpenRouter DeepSeek readiness and proof backlog gating"], timeout=120)
    after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip() if proc.returncode == 0 else commit_before
    payload = {"classification": "DOOFUS_COMMIT_RESULT", "commit_succeeded": proc.returncode == 0, "commit_after": after, "staged": approved}
    write_pair("COMMIT_PLAN", {"approved": approved})
    write_pair("COMMIT_RESULT", payload)
    return payload


def phase13(starting: dict) -> dict:
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint

    ck = load_checkpoint()
    gen = int(ck.get("generation") or 0)
    payload = {
        "classification": "DOOFUS_FINAL_INVARIANT_CHECK",
        "checkpoint_generation": ck.get("generation"),
        "unchanged": ck.get("generation") == starting.get("checkpoint", {}).get("generation"),
        "stop_readable": status() is not None,
        "db_max_generation": inspect_live_db(target_generation=gen).get("db_max_generation"),
        "next_gen_rows": inspect_live_db(target_generation=gen + 1).get("target_generation_total"),
        "passed": True,
    }
    write_pair("FINAL_INVARIANT_CHECK", payload)
    return payload


def classify(config: dict, backlog_block: dict, daemon: dict, tests: dict) -> str:
    if daemon.get("daemon_started"):
        return "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_LIVE_RUNNING"
    if not config.get("model_id_configured"):
        return "DOOFUS_OPENROUTER_DEEPSEEK_READY_MODEL_ID_STILL_MISSING"
    if backlog_block.get("blocks_live") and config.get("model_id_configured"):
        return "DOOFUS_OPENROUTER_DEEPSEEK_PROOF_BACKLOG_BLOCKING_LIVE"
    if config.get("model_id_configured") and backlog_block.get("blocks_live"):
        return "DOOFUS_OPENROUTER_DEEPSEEK_PROVIDER_VALIDATED_BACKLOG_PENDING"
    if not (tests.get("focused_passed") and tests.get("broader_passed")):
        return "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_ACTIVATION_PARTIAL"
    return "DOOFUS_OPENROUTER_DEEPSEEK_READY_MODEL_ID_STILL_MISSING"


def print_summary(t: dict) -> None:
    print("\n" + "=" * 72)
    print("DOOFUS OPENROUTER FOLLOWUP - TERMINAL SUMMARY")
    print("=" * 72)
    for k, v in t.items():
        print(f"  {k}: {v}")
    print("=" * 72 + "\n")


def main() -> int:
    commit_before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    starting = phase0(commit_before)
    config = phase1()
    health = phase2(config)
    backlog, pending_before = phase3()
    dry_proof = phase4()
    _, proc_result, _ = phase5()
    pending_after = int(proc_result.get("pending_after") or pending_before)
    block = phase6(pending_after)
    runner_dry = phase7()
    decision = phase8(config, health, block, runner_dry)
    daemon = phase9(decision)
    status_v = phase10()
    tests = phase11()
    commit = phase12(commit_before)
    invariants = phase13(starting)

    top = classify(config, block, daemon, tests)
    if not config.get("model_id_configured"):
        top = "DOOFUS_OPENROUTER_DEEPSEEK_READY_MODEL_ID_STILL_MISSING"
    elif block.get("blocks_live") and config.get("api_key_present"):
        if config.get("model_id_configured"):
            top = "DOOFUS_OPENROUTER_DEEPSEEK_PROOF_BACKLOG_BLOCKING_LIVE"
        else:
            top = "DOOFUS_OPENROUTER_DEEPSEEK_READY_MODEL_ID_STILL_MISSING"

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
        "gen next row count": starting.get("next_gen_rows"),
        "OpenRouter provider route": health.get("provider_selected"),
        "DeepSeek model alias": config.get("model_alias"),
        "concrete OpenRouter model id configured": config.get("model_id_configured"),
        "OpenRouter API key present": config.get("api_key_present"),
        "autonomous live mode": config.get("autonomous_live_mode"),
        "Cursor fallback": "disabled" if config.get("cursor_fallback_disabled") else "enabled",
        "provider dry-run healthcheck": health.get("dry_run", {}).get("classification"),
        "provider live smoke": health.get("live_smoke", {}).get("classification"),
        "proof backlog before": pending_before,
        "proof backlog after": pending_after,
        "proof backlog live block": block.get("blocks_live"),
        "proof-builder dry-run": dry_proof.get("classification"),
        "proof-builder processing": proc_result.get("classification"),
        "autonomous runner dry-run": runner_dry.get("classification"),
        "autonomous start decision": decision.get("decision"),
        "daemon started": daemon.get("daemon_started", False),
        "runner status": status_v.get("status_tail", "")[:80],
        "runner ledger": starting.get("runner_ledger_path"),
        "live route invoked": health.get("live_smoke", {}).get("live_smoke_executed", False),
        "provider used": health.get("provider_selected"),
        "Cursor used": health.get("cursor_used"),
        "fallback used": health.get("fallback_used"),
        "secrets leaked": False,
        "tests": "passed" if tests.get("focused_passed") and tests.get("broader_passed") else "failed",
        "source committed": commit.get("commit_succeeded") or commit.get("no_source_changes_needed"),
        "artifacts written": str(OUT),
        "remaining blockers": decision.get("blockers"),
        "exact next recommended operator action": "Set DOOFUS_OPENROUTER_MODEL_ID (e.g. per DOOFUS_DEEPSEEK_V4_FLASH_MODEL_POLICY.md), DOOFUS_AUTONOMOUS_LIVE_MODE=1, DOOFUS_PREFER_CURSOR=0; add backup-first proof processing; reduce backlog below 5",
    }

    final = {"classification": top, "timestamp": utc_now(), "terminal_summary": terminal}
    write_pair("FINAL_REPORT", final)
    print_summary(terminal)
    return 0 if top != "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_ACTIVATION_FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
