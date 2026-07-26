"""Supervisor watchdog — detect stale heartbeat, duplicate PIDs, restart tasks."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time

from doofus.core.doofus_paths import ROOT, STATE
from doofus.safety.on_off_switch import status as switch_status
from doofus.supervisor.heartbeat_watchdog import heartbeat_status
from doofus.supervisor.process_singleton import read_singleton_pid
from doofus.supervisor.scheduled_task_guard import get_scheduled_task_states, restart_task
from doofus.dashboard.dashboard_health import classify_dashboard_health

CHECK_INTERVAL = int(os.environ.get("DOOFUS_WATCHDOG_CHECK_SECONDS", "60"))


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, PermissionError):
        return False


def count_doofus_python_processes() -> int:
    """Count live Doofus singleton processes via lock files (no WMI — hangs on some hosts)."""
    from doofus.runtime.process_registry import PROTECTED_ROLES

    n = 0
    for role in PROTECTED_ROLES:
        pid = read_singleton_pid(role)
        if pid and _pid_alive(pid):
            n += 1
    return n


def duplicate_pid_report() -> dict:
    n = count_doofus_python_processes()
    sup_pid = read_singleton_pid("doofus_supervisor")
    dash_pid = read_singleton_pid("doofus_dashboard")
    alive_sup = _pid_alive(sup_pid) if sup_pid else False
    alive_dash = _pid_alive(dash_pid) if dash_pid else False
    stale_locks = (sup_pid and not alive_sup) or (dash_pid and not alive_dash)
    return {
        "doofus_python_count": n,
        "supervisor_lock_pid": sup_pid,
        "dashboard_lock_pid": dash_pid,
        "supervisor_lock_alive": alive_sup,
        "dashboard_lock_alive": alive_dash,
        "duplicate_detected": n > 3 or stale_locks,
    }


def run_watchdog_once(*, allow_restart: bool = True) -> dict:
    sw = switch_status()
    hb = heartbeat_status()
    tasks = get_scheduled_task_states()
    dupes = duplicate_pid_report()
    dash_health = classify_dashboard_health(tasks.get("dashboard_state"))
    actions: list[str] = []

    if sw.get("emergency_stop"):
        return {
            "classification": "WATCHDOG_IDLE_EMERGENCY",
            "actions": [],
            "switch": sw,
            "heartbeat": hb,
            "tasks": tasks,
            "duplicates": dupes,
            "dashboard_health": dash_health,
        }

    if dupes["duplicate_detected"] and allow_restart and not sw.get("stop_requested"):
        from doofus.runtime.safe_cleanup import run_safe_cleanup
        run_safe_cleanup()
        actions.append("cleanup_stale_locks")

    sup_stopped = tasks.get("supervisor_state") != "Running"
    if (sup_stopped or hb.get("stale_restart")) and sw.get("may_run") and allow_restart:
        from doofus.runtime.runtime_repair import ensure_supervisor
        rep = ensure_supervisor()
        if rep.get("started"):
            actions.append("restart_supervisor")

    if dash_health.get("needs_restart") and allow_restart:
        from doofus.runtime.runtime_repair import ensure_dashboard
        rep = ensure_dashboard()
        if rep.get("started"):
            actions.append("restart_dashboard_dead_ui")

    result = {
        "classification": "WATCHDOG_OK" if not actions else "WATCHDOG_ACTION",
        "actions": actions,
        "switch": sw,
        "heartbeat": hb,
        "tasks": tasks,
        "duplicates": dupes,
        "dashboard_health": dash_health,
        "bind_verified": dash_health.get("bind_host") == "127.0.0.1" and not dash_health.get("public_bind"),
    }
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "watchdog_last.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--loop", action="store_true")
    args = p.parse_args()
    if args.loop:
        while True:
            r = run_watchdog_once()
            print(json.dumps({"classification": r["classification"], "actions": r["actions"]}))
            time.sleep(CHECK_INTERVAL)
        return 0
    r = run_watchdog_once()
    print(json.dumps(r, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
