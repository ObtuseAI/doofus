"""Capture runtime metrics snapshot for burn-in baseline / post comparison."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doofus.core.doofus_config import DoofusConfig
from doofus.core.doofus_paths import METRICS_DB, ROOT, DUNCE_HANDOFF, BURN_IN_AUDIT_DIR
from doofus.core.doofus_state import init_db

AUDIT_DIR = BURN_IN_AUDIT_DIR


def _git_head() -> str:
    try:
        head_file = ROOT / ".git" / "HEAD"
        if not head_file.exists():
            return "unknown"
        ref = head_file.read_text(encoding="utf-8").strip()
        if ref.startswith("ref:"):
            ref_path = ROOT / ".git" / ref.split(":", 1)[1].strip()
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()
            return ref
        return ref
    except Exception:
        return "unknown"


def _duplicate_pid_count() -> int:
    try:
        from doofus.supervisor.supervisor_watchdog import count_doofus_python_processes
        from doofus.runtime.process_registry import PROTECTED_ROLES
        from doofus.supervisor.process_singleton import read_singleton_pid, _pid_alive

        n = count_doofus_python_processes()
        expected = sum(1 for role in PROTECTED_ROLES if read_singleton_pid(role) and _pid_alive(read_singleton_pid(role) or 0))
        return max(0, n - expected) if n > len(PROTECTED_ROLES) else 0
    except Exception:
        return 0


def _sqlite_probe() -> dict:
    try:
        init_db()
        conn = sqlite3.connect(METRICS_DB, timeout=2.0)
        conn.execute("SELECT 1")
        conn.close()
        return {"accessible": True, "locked": False, "error": None}
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        return {"accessible": False, "locked": "locked" in msg, "error": type(exc).__name__}
    except Exception as exc:
        return {"accessible": False, "locked": False, "error": type(exc).__name__}


def _count_since(conn: sqlite3.Connection, table: str, since: str | None) -> int:
    if since:
        row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE created_at >= ?", (since,)).fetchone()
    else:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0]) if row else 0


def _events_like_since(conn: sqlite3.Connection, table: str, pattern: str, since: str | None) -> int:
    sql = f"SELECT COUNT(*) FROM {table} WHERE detail LIKE ?"
    params: tuple[Any, ...] = (f"%{pattern}%",)
    if since:
        sql += " AND created_at >= ?"
        params = (f"%{pattern}%", since)
    return int(conn.execute(sql, params).fetchone()[0])


def capture_metrics_snapshot(*, label: str = "snapshot") -> dict:
    """Full runtime snapshot — no secrets."""
    from doofus.dashboard.live_data_api import get_model_auth_status, get_budget_rate_status
    from doofus.dashboard.live_state_reader import read_latest_error
    from doofus.dashboard.live_task_reader import get_task_status
    from doofus.safety.on_off_switch import status as switch_status

    init_db()
    cfg = DoofusConfig.from_env()
    sw = switch_status()
    auth = get_model_auth_status()
    budget = get_budget_rate_status()
    tasks = get_task_status()
    sqlite_status = _sqlite_probe()

    conn = sqlite3.connect(METRICS_DB, timeout=2.0)
    counts = {
        "candidates": conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
        "promotions": conn.execute("SELECT COUNT(*) FROM promotions").fetchone()[0],
        "rejections": conn.execute("SELECT COUNT(*) FROM rejections").fetchone()[0],
        "mutations": conn.execute("SELECT COUNT(*) FROM mutations").fetchone()[0],
        "arena_results": conn.execute("SELECT COUNT(*) FROM arena_results").fetchone()[0],
        "lineage_rows": conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE parent_id IS NOT NULL AND parent_id != ''"
        ).fetchone()[0],
        "model_calls": conn.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0],
        "safety_events": conn.execute("SELECT COUNT(*) FROM safety_events").fetchone()[0],
        "heartbeats": conn.execute("SELECT COUNT(*) FROM heartbeats").fetchone()[0],
        "cycles": conn.execute("SELECT COUNT(*) FROM cycles").fetchone()[0],
    }
    cost_row = conn.execute("SELECT COALESCE(SUM(cost_est),0) FROM model_calls").fetchone()
    successful_live = conn.execute(
        "SELECT COUNT(*) FROM model_calls WHERE provider NOT IN ('dry_run','none','')"
    ).fetchone()[0]
    rate_limit_events = _events_like_since(conn, "safety_events", "429", None)
    rate_limit_events += _events_like_since(conn, "dashboard_events", "rate_limit", None)
    cooldown_events = _events_like_since(conn, "dashboard_events", "cooldown", None)
    cooldown_events += _events_like_since(conn, "safety_events", "cooldown", None)
    shadow = conn.execute("SELECT COUNT(*) FROM candidates WHERE promotion_status='shadow_promoted'").fetchone()[0]
    hb = conn.execute("SELECT created_at, status FROM heartbeats ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()

    from doofus.evolution.evolution_pressure_mode import get_evolution_snapshot
    from doofus.scoring.promotion_quarantine import debt_summary
    from doofus.supervisor.heartbeat_watchdog import heartbeat_status

    evo = get_evolution_snapshot()
    debt = debt_summary()
    hb_info = heartbeat_status()

    dunce_mtime_before = None
    if DUNCE_HANDOFF.exists():
        try:
            dunce_mtime_before = DUNCE_HANDOFF.stat().st_mtime
        except OSError:
            pass

    return {
        "label": label,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "may_run": sw.get("may_run", False),
        "run_enabled": sw.get("run_enabled", False),
        "emergency_stop": sw.get("emergency_stop", False),
        "stop_request": sw.get("stop_requested", False),
        "dashboard_bind": f"{cfg.dashboard_host}:{cfg.dashboard_port}",
        "dashboard_host": cfg.dashboard_host,
        "provider_selected": auth.get("provider_selected"),
        "active_model": auth.get("active_model"),
        "live_provider_ready": auth.get("live_provider_ready", False),
        "deepseek_openrouter_ready": auth.get("deepseek_openrouter_ready", False),
        "provider_auth_status": auth.get("provider_auth"),
        "model_call_count": counts["model_calls"],
        "successful_live_calls": successful_live,
        "estimated_cost": float(cost_row[0]) if cost_row else 0.0,
        "budget_guard_ok": budget.get("ok", False),
        "rate_guard_ok": budget.get("calls_last_hour", 0) < budget.get("max_calls_per_hour", 60),
        "budget": budget,
        "candidate_count": counts["candidates"],
        "promotion_count": counts["promotions"],
        "shadow_promotion_count": shadow,
        "rejection_count": counts["rejections"],
        "lineage_rows": counts["lineage_rows"],
        "mutation_rows": counts["mutations"],
        "arena_result_rows": counts["arena_results"],
        "safety_event_count": counts["safety_events"],
        "heartbeat_timestamp": hb[0] if hb else None,
        "heartbeat_status": hb[1] if hb else None,
        "latest_error": read_latest_error() or "none",
        "sqlite": sqlite_status,
        "duplicate_pid_count": _duplicate_pid_count(),
        "rate_limit_events_total": rate_limit_events,
        "cooldown_events_total": cooldown_events,
        "supervisor_task": tasks.get("Doofus-24-7-Supervisor", {}),
        "dashboard_task": tasks.get("Doofus-Local-Dashboard", {}),
        "dunce_handoff_mtime": dunce_mtime_before,
        "dunce_handoff_path": str(DUNCE_HANDOFF),
        "evolution_pressure_level": evo.get("pressure_level"),
        "stagnation_cycles": evo.get("stagnation_cycles"),
        "elite_archive_count": evo.get("elite_archive_count"),
        "best_ever_score": evo.get("best_ever_score"),
        "best_ever_candidate_id": evo.get("best_ever_candidate_id"),
        "challenger_tournament_count": evo.get("challenger_tournament_count"),
        "retired_branch_count": evo.get("retired_branch_count"),
        "proof_debt_count": debt.get("proof_debt_count"),
        "arena_debt_count": debt.get("arena_debt_count"),
        "heartbeat_age_seconds": hb_info.get("age_seconds"),
    }


def save_snapshot(path: Path, snapshot: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return path


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
