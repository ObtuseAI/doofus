"""Hourly autopilot — watch, evaluate, improve for a fixed duration."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STOP_FILE = ROOT / "runtime" / "control" / "DOOFUS_AUTOPILOT_STOP.request"
SESSION_LOG = ROOT / "runtime" / "state" / "autopilot_sessions.jsonl"
STATE_FILE = ROOT / "runtime" / "state" / "autopilot_last.json"
PY = ROOT / ".venv_doofus" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stopped() -> bool:
    return STOP_FILE.exists()


def _append_session(row: dict) -> None:
    SESSION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SESSION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _save_last(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    from doofus.core.atomic_json import save_json
    save_json(STATE_FILE, state)


def _ensure_runtime() -> dict:
    from doofus.safety.on_off_switch import clear_emergency, start, status
    from doofus.config.proof_builder_runtime_config import bootstrap_autonomous_runtime
    from doofus.config.meta_evolution_config import apply_defaults as apply_meta
    from doofus.runtime.runtime_repair import ensure_supervisor

    print(json.dumps({"phase": "bootstrap_start", "at": _utc()}), flush=True)
    clear_emergency()
    start()
    apply_meta(force=False)
    bootstrap_autonomous_runtime(force=False)
    sup = ensure_supervisor()
    out = {"switch": status(), "supervisor": sup}
    print(json.dumps({"phase": "bootstrap_done", **out}, default=str), flush=True)
    return out


def _watch(*, allow_repairs: bool = False) -> dict:
    from doofus.meta.recursive_supervisor import get_meta_snapshot
    from doofus.safety.on_off_switch import status as switch_status

    print(json.dumps({"phase": "watch_start", "at": _utc()}), flush=True)
    meta = get_meta_snapshot()
    sw = switch_status()
    pipe_log = ROOT / "runtime" / "logs" / "pipeline.log"
    recent_errors = 0
    if pipe_log.exists():
        tail = pipe_log.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]
        recent_errors = sum(1 for ln in tail if "WARNING" in ln or "ERROR" in ln)
    try:
        from doofus.supervisor.heartbeat_watchdog import heartbeat_status
        hb = heartbeat_status()
        watch = {
            "classification": "WATCHDOG_STALE" if hb.get("stale_restart") else "WATCHDOG_OK",
            "heartbeat": hb,
        }
    except Exception as exc:
        watch = {"classification": "WATCHDOG_ERROR", "error": type(exc).__name__}
    dash = {"classification": "DASHBOARD_WATCHDOG_SKIPPED"}
    generation = None
    best_ever = None
    try:
        from doofus.core.doofus_paths import METRICS_DB
        import sqlite3
        conn = sqlite3.connect(METRICS_DB, timeout=1.0)
        row = conn.execute("SELECT MAX(generation) FROM cycles").fetchone()
        generation = int(row[0]) if row and row[0] is not None else None
        row2 = conn.execute(
            "SELECT MAX(score) FROM candidates WHERE promotion_status IN ('promoted','shadow_promoted')"
        ).fetchone()
        best_ever = float(row2[0]) if row2 and row2[0] is not None else None
        conn.close()
    except Exception:
        pass
    out = {
        "classification": "AUTOPILOT_WATCH",
        "metrics": {
            "generation": generation,
            "may_run": sw.get("may_run"),
            "best_ever": best_ever,
            "stagnation": meta.get("state", {}).get("last_inner"),
            "pipeline_warnings": recent_errors,
        },
        "watchdog": watch.get("classification"),
        "dashboard_watchdog": dash.get("classification"),
    }
    print(json.dumps({"phase": "watch_done", "generation": generation}, default=str), flush=True)
    return out


def _evaluate() -> dict:
    from doofus.evolution.adaptive_mutation_pressure import get_pressure_state
    from doofus.evolution.map_elites_archive import get_snapshot as map_snap
    from doofus.meta.gepa.prompt_store import snapshot as gepa_snap
    from doofus.meta.gep.capsule_store import get_snapshot as gep_snap
    from doofus.meta.aevolve.algorithm_selector import get_snapshot as aev_snap

    ps = get_pressure_state()
    stagnation = int(ps.get("stagnation_cycles") or 0)
    issues: list[str] = []
    if stagnation >= 10:
        issues.append("high_stagnation")
    if int(ps.get("candidate_count_next") or 0) < 8:
        issues.append("low_candidate_pressure")
    return {
        "classification": "AUTOPILOT_EVALUATE",
        "pressure": ps,
        "map_elites": map_snap(),
        "gepa": gepa_snap(),
        "gep": gep_snap(),
        "aevolve": aev_snap(),
        "issues": issues,
        "needs_improvement": bool(issues),
    }


def _improve(eval_result: dict, *, tick_index: int, run_heavy: bool) -> dict:
    actions: list[dict] = []
    from doofus.safety.budget_guard import check_budget
    from doofus.core.doofus_config import DoofusConfig
    from doofus.safety.on_off_switch import check_may_proceed

    ok, reason = check_may_proceed()
    budget = check_budget(DoofusConfig.from_env())
    if not ok:
        return {"classification": "AUTOPILOT_IMPROVE_SKIPPED", "reason": reason}
    if not budget.get("ok"):
        return {"classification": "AUTOPILOT_IMPROVE_BUDGET", "budget": budget}

    issues = eval_result.get("issues") or []
    # Escalate at most twice per session (tick 0 and mid-session) — not every tick
    if "high_stagnation" in issues and tick_index in (0, 6):
        from doofus.meta.aevolve.stagnation_escalator import escalate
        actions.append({"action": "aevolve_escalate", "result": escalate(int(eval_result["pressure"].get("stagnation_cycles", 10)))})

    # Light improvements (skip tick 0 — let first watch/eval complete quickly)
    if tick_index > 0 and tick_index % 2 == 0:
        try:
            from doofus.meta.gepa.prompt_evolver import run_batch
            gepa = run_batch(force=("high_stagnation" in issues))
            actions.append({"action": "gepa_batch", "result": gepa.get("classification")})
        except Exception as exc:
            actions.append({"action": "gepa_batch", "error": type(exc).__name__})

    if tick_index > 0 and tick_index % 3 == 0:
        try:
            from doofus.evolution.map_elites_archive import maintain
            actions.append({"action": "map_maintain", "result": maintain().get("classification")})
        except Exception as exc:
            actions.append({"action": "map_maintain", "error": type(exc).__name__})

    # Meta cycles run in the 24/7 supervisor — autopilot only monitors + light meta tweaks
    print(json.dumps({"phase": "improve_done", "tick": tick_index, "actions": len(actions)}, default=str), flush=True)
    return {"classification": "AUTOPILOT_IMPROVE", "actions": actions, "tick_index": tick_index, "heavy": run_heavy}


def _session_cleanup() -> dict:
    try:
        from doofus.runtime.session_cleanup import cleanup_after_autopilot_session
        result = cleanup_after_autopilot_session()
        print(json.dumps({"phase": "session_cleanup", "killed": len(result.get("killed") or [])}, default=str), flush=True)
        return result
    except Exception as exc:
        err = {"classification": "SESSION_CLEANUP_ERROR", "error": type(exc).__name__}
        print(json.dumps({"phase": "session_cleanup_error", **err}, default=str), flush=True)
        return err


def run_session(*, duration_minutes: int = 20, interval_seconds: int = 90) -> dict:
    if _stopped():
        return {"classification": "AUTOPILOT_STOPPED", "reason": "stop_file"}

    STOP_FILE.unlink(missing_ok=True)
    session_id = f"autopilot_{int(time.time())}"
    started = _utc()
    wall_start = time.monotonic()
    runtime = _ensure_runtime()
    ticks: list[dict] = []
    deadline = time.monotonic() + duration_minutes * 60
    tick_index = 0

    while time.monotonic() < deadline:
        if _stopped():
            break
        tick_start = _utc()
        try:
            watch = _watch(allow_repairs=False)
            ev = _evaluate()
            print(json.dumps({"phase": "evaluate_done", "issues": ev.get("issues")}, default=str), flush=True)
            imp = _improve(ev, tick_index=tick_index, run_heavy=True)
        except Exception as exc:
            watch = {"classification": "AUTOPILOT_WATCH_ERROR", "error": type(exc).__name__}
            ev = {"classification": "AUTOPILOT_EVALUATE_ERROR", "error": type(exc).__name__}
            imp = {"classification": "AUTOPILOT_IMPROVE_ERROR", "error": type(exc).__name__}
            print(json.dumps({"phase": "tick_error", "tick": tick_index, "error": type(exc).__name__}, default=str), flush=True)
        tick = {"at": tick_start, "watch": watch, "evaluate": ev, "improve": imp}
        ticks.append(tick)
        _append_session({"session_id": session_id, **tick})
        print(json.dumps({"tick": tick_index, "promoted": imp.get("actions"), "generation": watch.get("metrics", {}).get("generation")}, default=str), flush=True)
        tick_index += 1
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval_seconds, remaining))

    wall_seconds = round(time.monotonic() - wall_start, 1)
    cleanup = _session_cleanup()
    summary = {
        "classification": "AUTOPILOT_SESSION_COMPLETE",
        "session_id": session_id,
        "started_at": started,
        "ended_at": _utc(),
        "duration_minutes": duration_minutes,
        "wall_clock_seconds": wall_seconds,
        "ticks": len(ticks),
        "runtime_bootstrap": runtime,
        "last_tick": ticks[-1] if ticks else {},
        "stopped_by_user": _stopped(),
        "session_cleanup": cleanup,
    }
    _save_last(summary)
    _append_session(summary)
    print(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--duration-minutes", type=int, default=20)
    p.add_argument("--interval-seconds", type=int, default=90)
    p.add_argument("--stop", action="store_true", help="Create stop file")
    args = p.parse_args()
    if args.stop:
        STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        STOP_FILE.write_text(f"stop_at={_utc()}\n", encoding="utf-8")
        print(json.dumps({"classification": "AUTOPILOT_STOP_REQUESTED"}))
        return 0
    run_session(duration_minutes=args.duration_minutes, interval_seconds=args.interval_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
