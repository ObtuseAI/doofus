"""Scheduled task status for dashboard — process-lock inference (no schtasks hang)."""
from __future__ import annotations

from doofus.supervisor.scheduled_task_guard import get_scheduled_task_states

TASKS = (
    "Doofus-Runtime-Manager",
    "Doofus-24-7-Supervisor",
    "Doofus-Local-Dashboard",
    "Doofus-24-7-Watchdog",
    "Doofus-Dashboard-Watchdog",
)


def get_task_status() -> dict:
    states = get_scheduled_task_states()
    key_map = {
        "Doofus-Runtime-Manager": "runtime_manager_state",
        "Doofus-24-7-Supervisor": "supervisor_state",
        "Doofus-Local-Dashboard": "dashboard_state",
        "Doofus-24-7-Watchdog": "watchdog_state",
        "Doofus-Dashboard-Watchdog": "dashboard_watchdog_state",
    }
    out = {}
    for name in TASKS:
        state = states.get(key_map[name], "unknown")
        out[name] = {
            "registered": state != "unknown",
            "state": state,
        }
    return out
