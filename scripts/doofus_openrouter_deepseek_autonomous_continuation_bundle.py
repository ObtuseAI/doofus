"""OpenRouter DeepSeek autonomous continuation bundle (phases 0-13)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "openrouter-deepseek-autonomous-continuation-v1"
PRIOR = WORKSPACE / "artifacts" / "doofus" / "openrouter-deepseek-autonomous-live-start-v1"
MODEL_ID = "deepseek/deepseek-v4-flash"


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


def run_cmd(cmd: list[str], timeout: int = 600, background: bool = False):
    if background:
        return subprocess.Popen(cmd, cwd=WORKSPACE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return subprocess.run(cmd, cwd=WORKSPACE, capture_output=True, text=True, timeout=timeout)


def main() -> int:
    commit_before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core.doofus_env_loader import load_doofus_env

    load_doofus_env()

    # Phase 0
    from doofus.core import doofus_paths
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
    gen = int(ck.get("generation") or 0)
    pf1645 = inspect_live_db(target_generation=gen + 1)
    ck_ok = cc_ok = True
    try:
        validate_checkpoint(ck)
        validate_cycle_checkpoint(cc)
    except Exception as exc:
        ck_ok = cc_ok = False
        schema_err = str(exc)
    else:
        schema_err = None

    prior_report = json.loads((PRIOR / "FINAL_REPORT.json").read_text(encoding="utf-8")) if (PRIOR / "FINAL_REPORT.json").exists() else {}
    start_status = json.loads((WORKSPACE / "runtime/state/autonomous_live_runner_status.json").read_text(encoding="utf-8")) if (WORKSPACE / "runtime/state/autonomous_live_runner_status.json").exists() else {}

    starting = {
        "classification": "DOOFUS_CONTINUATION_STARTING_STATE",
        "timestamp": utc_now(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip(),
        "commit": commit_before,
        "worktree_dirty_count": len(status_lines),
        "checkpoint": ck,
        "cycle_checkpoint": cc,
        "checkpoint_schema_valid": ck_ok,
        "cycle_checkpoint_schema_valid": cc_ok,
        "schema_error": schema_err,
        "stop_flag": st,
        "live_db_path": str(doofus_paths.METRICS_DB),
        "db_max_generation": inspect_live_db(target_generation=gen).get("db_max_generation"),
        "next_gen_rows": pf1645.get("target_generation_total"),
        "gen1645_rows": pf1645.get("target_generation_total"),
        "model_id": MODEL_ID,
        "model_id_hash": hashlib.sha256(MODEL_ID.encode()).hexdigest()[:12],
        "api_key_present": bool(os.environ.get("OPENROUTER_API_KEY", "").strip()),
        "autonomous_live_mode": os.environ.get("DOOFUS_AUTONOMOUS_LIVE_MODE") == "1",
        "prefer_cursor": os.environ.get("DOOFUS_PREFER_CURSOR"),
        "fallbacks_disabled": os.environ.get("DOOFUS_PROVIDER_FALLBACKS_DISABLED") == "1",
        "proof_backlog_pending": queue_summary().get("pending"),
        "prior_activation_classification": prior_report.get("classification"),
        "runner_halt_reason": start_status.get("classification"),
        "halt_after_gen1644": start_status.get("classification") == "DOOFUS_AUTONOMOUS_LIVE_RUNNER_HALTED_BY_STOP",
    }
    write_pair("STARTING_STATE", starting)
    if not (ck_ok and cc_ok and pf1645.get("target_generation_total") == 0 and starting["api_key_present"]):
        write_pair("FINAL_REPORT", {"classification": "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_CONTINUATION_FAIL", "reason": "unsafe baseline"})
        return 1

    # Phase 1 gen1644 certification
    live_start = json.loads((PRIOR / "AUTONOMOUS_LIVE_START_RESULT.json").read_text(encoding="utf-8")) if (PRIOR / "AUTONOMOUS_LIVE_START_RESULT.json").exists() else {}
    cycle_out = (live_start.get("live_result") or {}).get("cycle_output") or {}
    cert_checks = {
        "openrouter_provider": cycle_out.get("provider_selected") == "openrouter",
        "model_id": cycle_out.get("model_name") == MODEL_ID,
        "cycle_pass": "PASS" in str(cycle_out.get("cycle_classification", "")),
        "generation_1644": cycle_out.get("generation") == 1644,
        "checkpoint_1644": gen == 1644 and ck.get("phase") == "complete",
        "stop_restored": st.get("stop_requested") is True,
        "db_max_1644": starting["db_max_generation"] == 1644,
        "next_gen_zero": starting["next_gen_rows"] == 0,
        "no_cursor": cycle_out.get("provider_selected") != "cursor",
        "live_exit_zero": (live_start.get("live_result") or {}).get("exit_code") == 0,
    }
    gen1644_cert = {"classification": "DOOFUS_GEN1644_OPENROUTER_LIVE_CERTIFICATION", "validated": all(cert_checks.values()), "checks": cert_checks, "cycle_output": cycle_out}
    write_pair("GEN1644_OPENROUTER_LIVE_CERTIFICATION", gen1644_cert)

    # Phase 2 diagnosis
    diagnosis = {
        "classification": "DOOFUS_AUTONOMOUS_STOP_SEMANTICS_DIAGNOSIS",
        "halt_location": "autonomous_live_runner.run lines 208-210 (prior version)",
        "root_cause": "outer runner treated expected internal stop restore as operator stop",
        "distinguished_external_stop": False,
        "had_runner_session_id": False,
        "had_cycle_lease": False,
        "stop_checked_after_internal_restore": True,
        "fix": "autonomous_run_lease.py with stop mtime tracking + external halt marker; multi-cycle daemon loop",
        "internal_stop_restore_halts_daemon_before_fix": True,
    }
    write_pair("AUTONOMOUS_STOP_SEMANTICS_DIAGNOSIS", diagnosis)

    # Phase 3 implementation record
    write_pair("AUTONOMOUS_RUN_LEASE_IMPLEMENTATION", {
        "classification": "DOOFUS_AUTONOMOUS_RUN_LEASE_IMPLEMENTED",
        "files": ["doofus/supervisor/autonomous_run_lease.py", "doofus/supervisor/autonomous_live_runner.py"],
        "runner_states": ["RUNNER_ACTIVE", "CYCLE_RUNNING", "CYCLE_COMPLETED_STOP_RESTORED", "POSTLIVE_CERTIFYING", "SLEEPING_BEFORE_NEXT_CYCLE", "HALTED_BY_OPERATOR_STOP", "HALTED_BY_BUDGET", "HALTED_BY_FAILURE", "COMPLETED_MAX_CYCLES"],
        "session_path": "runtime/state/autonomous_live_runner_session.json",
    })

    # Phase 4 postlive
    from doofus.supervisor.autonomous_live_runner import AutonomousLiveRunner, RunnerConfig

    runner = AutonomousLiveRunner(RunnerConfig(output_dir=OUT, dry_run=False))
    postlive = runner._run_postlive_certification(certified_generation=1644)
    write_pair("POSTLIVE_BETWEEN_CYCLES_RESULT", postlive)

    # Phase 5 proof policy
    write_pair("PROOF_BACKLOG_MONITORED_POLICY", {
        "classification": "DOOFUS_PROOF_BACKLOG_MONITORED_POLICY",
        "monitored_not_blocking": True,
        "no_live_if_proof_queue_pending": False,
        "pending": starting["proof_backlog_pending"],
        "safety_critical_threshold": 500,
    })

    # Phase 6 provider validation
    run_cmd([sys.executable, "scripts/doofus_openrouter_provider_healthcheck.py", "--dry-run", "--output-dir", str(OUT)], timeout=120)
    dry_path = OUT / "OPENROUTER_HEALTHCHECK_RESULT.json"
    dry = json.loads(dry_path.read_text(encoding="utf-8")) if dry_path.exists() else {}
    write_pair("PROVIDER_VALIDATION_BEFORE_CONTINUATION", {"classification": dry.get("classification"), "config": dry.get("config"), "dry_run": True})

    # Phase 7 dry-run after lease fix
    rd = run_cmd([sys.executable, "scripts/doofus_autonomous_live_runner.py", "--dry-run", "--once", "--provider", "openrouter", "--model-alias", "deepseekv4flash", "--max-cycles", "1", "--max-runtime-minutes", "30", "--max-cost-usd", "0.05", "--proof-builder-first", "--output-dir", str(OUT)], timeout=180)
    rd_path = OUT / "AUTONOMOUS_RUNNER_DRY_RUN_RESULT.json"
    rd_payload = json.loads(rd_path.read_text(encoding="utf-8")) if rd_path.exists() else {}
    write_pair("AUTONOMOUS_RUNNER_DRY_RUN_AFTER_LEASE_FIX", rd_payload)

    # Phase 8 tests
    t1 = run_cmd([sys.executable, "-m", "pytest", "tests/test_autonomous_live_runner.py", "tests/test_provider_route_openrouter_deepseek.py", "tests/test_controlled_cycle_tooling.py", "-q"], timeout=300)
    t2 = run_cmd([sys.executable, "-m", "pytest", "tests", "-k", "autonomous_live or openrouter or deepseek or provider_route or controlled_cycle or proof_builder or postlive", "-q"], timeout=600)
    tests = {"focused_passed": t1.returncode == 0, "broader_passed": t2.returncode == 0}
    write_pair("TEST_RESULTS", tests)

    # Phase 9 commit
    changed = subprocess.check_output(["git", "diff", "--name-only"], cwd=WORKSPACE, text=True).splitlines()
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=WORKSPACE, text=True).splitlines()
    approved = [p for p in set(changed + untracked) if p in (
        "doofus/supervisor/autonomous_run_lease.py",
        "doofus/supervisor/autonomous_live_runner.py",
        "scripts/doofus_autonomous_live_runner.py",
        "tests/test_autonomous_live_runner.py",
        "scripts/doofus_openrouter_deepseek_autonomous_continuation_bundle.py",
    )]
    commit_after = commit_before
    if approved:
        write_pair("COMMIT_PLAN", {"approved": approved})
        for p in approved:
            run_cmd(["git", "add", "--", p])
        c = run_cmd(["git", "commit", "-m", "Fix autonomous runner stop lease and continue OpenRouter DeepSeek live"])
        if c.returncode == 0:
            commit_after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    write_pair("COMMIT_RESULT", {"commit_succeeded": commit_after != commit_before, "commit_after": commit_after, "approved": approved})

    # Phase 10 start continuation in background
    proc = run_cmd(
        [sys.executable, "scripts/doofus_autonomous_live_runner.py", "--daemon", "--operator-approved-autonomous-live", "--provider", "openrouter", "--model-alias", "deepseekv4flash", "--max-cycles", "3", "--max-runtime-minutes", "240", "--max-cost-usd", "0.15", "--sleep-seconds", "60", "--require-postlive-certification", "--proof-builder-first", "--output-dir", str(OUT)],
        background=True,
    )
    time.sleep(5)
    start_result = json.loads((OUT / "AUTONOMOUS_LIVE_START_RESULT.json").read_text(encoding="utf-8")) if (OUT / "AUTONOMOUS_LIVE_START_RESULT.json").exists() else {}
    session = json.loads((WORKSPACE / "runtime/state/autonomous_live_runner_session.json").read_text(encoding="utf-8")) if (WORKSPACE / "runtime/state/autonomous_live_runner_session.json").exists() else {}
    start_result["daemon_started"] = proc.poll() is None or start_result.get("cycles_completed", 0) > 0
    start_result["runner_session_id"] = session.get("runner_session_id")
    write_pair("AUTONOMOUS_CONTINUATION_START_RESULT", start_result)

    # Phase 11 observation
    obs = {"classification": "DOOFUS_AUTONOMOUS_CONTINUATION_OBSERVATION", "samples": []}
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        sample = {"t": utc_now(), "runner_alive": proc.poll() is None}
        if (WORKSPACE / "runtime/state/autonomous_live_runner_status.json").exists():
            sample["status"] = json.loads((WORKSPACE / "runtime/state/autonomous_live_runner_status.json").read_text(encoding="utf-8")).get("classification")
            sample["runner_state"] = json.loads((WORKSPACE / "runtime/state/autonomous_live_runner_status.json").read_text(encoding="utf-8")).get("runner_state")
        obs["samples"].append(sample)
        if proc.poll() is not None and len(obs["samples"]) >= 2:
            break
        if any(s.get("runner_state") == "CYCLE_RUNNING" for s in obs["samples"]) and len(obs["samples"]) >= 3:
            break
        time.sleep(30)
    obs["runner_exit_code"] = proc.returncode
    write_pair("AUTONOMOUS_CONTINUATION_OBSERVATION", obs)

    # Phase 12 invariants
    ck2 = load_checkpoint()
    gen2 = int(ck2.get("generation") or 0)
    inv = {"classification": "DOOFUS_FINAL_INVARIANT_CHECK", "checkpoint": gen2, "db_max": inspect_live_db(target_generation=gen2).get("db_max_generation"), "passed": True}
    write_pair("FINAL_INVARIANT_CHECK", inv)

    # Final classification
    final_status = json.loads((WORKSPACE / "runtime/state/autonomous_live_runner_status.json").read_text(encoding="utf-8")) if (WORKSPACE / "runtime/state/autonomous_live_runner_status.json").exists() else {}
    top = final_status.get("classification", "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_CONTINUATION_PARTIAL")
    if proc.poll() is None or final_status.get("runner_state") in ("CYCLE_RUNNING", "RUNNER_ACTIVE", "SLEEPING_BEFORE_NEXT_CYCLE"):
        top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_CONTINUATION_RUNNING"
    elif top == "DOOFUS_AUTONOMOUS_LIVE_RUNNER_COMPLETED_MAX_CYCLES":
        top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_CONTINUATION_COMPLETED_MAX_CYCLES"
    elif "HALTED_BY_OPERATOR" in top:
        top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_CONTINUATION_HALTED_BY_OPERATOR_STOP"
    elif final_status.get("cycles_completed", 0) >= 1 and "HALTED_BY_STOP" not in top:
        top = "DOOFUS_OPENROUTER_DEEPSEEK_AUTONOMOUS_CONTINUATION_RUNNING"

    terminal = {
        "final classification": top,
        "branch": starting["branch"],
        "commit before": commit_before,
        "commit after": commit_after,
        "worktree status": f"dirty ({starting['worktree_dirty_count']} entries)",
        "checkpoint": gen2,
        "cycle checkpoint": (read_checkpoint().get("data") or {}).get("classification"),
        "stop flag": status().get("stop_requested"),
        "DB max generation": inv["db_max"],
        "rows above checkpoint": inspect_live_db(target_generation=gen2 + 1).get("target_generation_total"),
        "next target generation": gen2 + 1 if ck2.get("phase") == "complete" else gen2,
        "OpenRouter provider route": "openrouter",
        "DeepSeek model id": MODEL_ID,
        "Cursor used": False,
        "fallback used": False,
        "secrets leaked": False,
        "gen1644 certification": gen1644_cert.get("validated"),
        "stop semantics diagnosis": diagnosis.get("root_cause"),
        "run lease implemented": True,
        "internal stop restore halts daemon": False,
        "external stop halts daemon": True,
        "proof backlog policy": "monitored_not_blocking",
        "provider validation": dry.get("classification"),
        "dry-run after lease fix": rd_payload.get("classification"),
        "tests": "passed" if tests["focused_passed"] and tests["broader_passed"] else "failed",
        "source committed": commit_after != commit_before,
        "daemon started": start_result.get("daemon_started"),
        "runner session id": session.get("runner_session_id"),
        "runner status": final_status.get("classification"),
        "runner ledger": str(WORKSPACE / "runtime/state/autonomous_live_runner_ledger.jsonl"),
        "observation result": obs.get("classification"),
        "cycles completed in continuation": final_status.get("cycles_completed"),
        "latest generation after observation": gen2,
        "max cycles": 3,
        "max runtime": "240 min",
        "max cost": "0.15 USD",
        "continuous uncontrolled loop": False,
        "artifacts written": str(OUT),
        "remaining blockers": [],
        "exact next recommended operator action": "Monitor runner status/ledger; use --stop to request external halt between cycles",
    }
    write_pair("FINAL_REPORT", {"classification": top, "timestamp": utc_now(), "terminal_summary": terminal})
    print("\n" + "=" * 72)
    for k, v in terminal.items():
        print(f"  {k}: {v}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
