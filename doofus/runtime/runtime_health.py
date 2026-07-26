"""Runtime health snapshot."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from doofus.core.doofus_paths import STATE, VENV, ROOT
from doofus.dashboard.dashboard_health import classify_dashboard_health, dashboard_reachable
from doofus.runtime.heartbeat_contract import classify_heartbeat_age
from doofus.runtime.process_registry import get_registry_snapshot, protected_pids
from doofus.safety.on_off_switch import status as switch_status
from doofus.supervisor.heartbeat_watchdog import heartbeat_age_seconds
from doofus.supervisor.process_singleton import read_singleton_pid, _pid_alive
from doofus.supervisor.scheduled_task_guard import get_scheduled_task_states

MANAGER_STATE = STATE / "runtime_manager_state.json"


def _manager_state() -> dict:
    if not MANAGER_STATE.exists():
        return {"active": False}
    try:
        return json.loads(MANAGER_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"active": False}


def supervisor_health() -> dict:
    age = heartbeat_age_seconds()
    hb = classify_heartbeat_age(age)
    pid = read_singleton_pid("doofus_supervisor")
    alive = _pid_alive(pid) if pid else False
    return {
        "active": alive and (not hb["stale"] if age is not None else True),
        "process_alive": alive,
        "lock_pid": pid,
        "heartbeat_age_seconds": age,
        **hb,
    }


def dashboard_health() -> dict:
    tasks = get_scheduled_task_states()
    health = classify_dashboard_health(tasks.get("dashboard_state"))
    pid = read_singleton_pid("doofus_dashboard")
    alive = _pid_alive(pid) if pid else False
    reachable = dashboard_reachable()
    if alive and reachable:
        health["classification"] = "process_alive_ui_alive"
    elif alive and not reachable:
        health["classification"] = "process_alive_ui_dead"
    health["process_alive"] = alive
    health["lock_pid"] = pid
    health["active"] = reachable
    return health


def runtime_manager_health() -> dict:
    pid = read_singleton_pid("doofus_runtime_manager")
    alive = _pid_alive(pid) if pid else False
    state = _manager_state()
    return {"active": alive, "process_alive": alive, "lock_pid": pid, **state}


def watchdog_health() -> dict:
    tasks = get_scheduled_task_states()
    registered = tasks.get("watchdog_registered") or tasks.get("dashboard_watchdog_registered")
    mgr = runtime_manager_health()
    return {
        "registered": registered,
        "active": registered or mgr.get("active"),
        "process_count": 0,
    }


def get_runtime_health() -> dict:
    sw = switch_status()
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "switch": sw,
        "runtime_manager": runtime_manager_health(),
        "supervisor": supervisor_health(),
        "dashboard": dashboard_health(),
        "watchdog": watchdog_health(),
        "tasks": get_scheduled_task_states(),
        "registry": get_registry_snapshot(),
        "protected_pids": sorted(protected_pids()),
        "python": str(VENV / "Scripts" / "python.exe"),
        "root": str(ROOT),
    }
