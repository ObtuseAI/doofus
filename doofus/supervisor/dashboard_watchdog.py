"""Dashboard watchdog — restart dashboard only when UI is dead."""
from __future__ import annotations

import argparse
import json
import time

from doofus.core.doofus_paths import STATE
from doofus.dashboard.dashboard_health import classify_dashboard_health
from doofus.supervisor.scheduled_task_guard import get_scheduled_task_states, restart_task
from doofus.supervisor.process_singleton import read_singleton_pid


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        import os
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, PermissionError):
        return False

CHECK_INTERVAL = 60


def run_dashboard_watchdog_once(*, allow_restart: bool = True) -> dict:
    tasks = get_scheduled_task_states()
    health = classify_dashboard_health(tasks.get("dashboard_state"))
    actions: list[str] = []
    dash_pid = read_singleton_pid("doofus_dashboard")

    if health["needs_restart"] and allow_restart:
        if dash_pid and _pid_alive(dash_pid) and not health["reachable"]:
            pass
        elif restart_task("Doofus-Local-Dashboard"):
            actions.append("restart_dashboard")

    result = {
        "classification": "DASHBOARD_WATCHDOG_OK" if not actions else "DASHBOARD_WATCHDOG_ACTION",
        "actions": actions,
        "health": health,
        "dashboard_lock_pid": dash_pid,
    }
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "dashboard_watchdog_last.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--loop", action="store_true")
    args = p.parse_args()
    if args.loop:
        while True:
            r = run_dashboard_watchdog_once()
            print(json.dumps({"classification": r["classification"], "actions": r["actions"]}))
            time.sleep(CHECK_INTERVAL)
        return 0
    r = run_dashboard_watchdog_once()
    print(json.dumps(r, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
