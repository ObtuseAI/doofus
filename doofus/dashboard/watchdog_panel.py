"""Watchdog dashboard panel."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import STATE
from doofus.supervisor.scheduled_task_guard import get_scheduled_task_states


def get_watchdog_panel() -> dict:
    tasks = get_scheduled_task_states()
    last = {}
    for name in ("watchdog_last.json", "dashboard_watchdog_last.json"):
        p = STATE / name
        if p.exists():
            last[name.replace(".json", "")] = json.loads(p.read_text(encoding="utf-8"))
    return {
        "supervisor_watchdog_registered": tasks.get("watchdog_registered", False),
        "dashboard_watchdog_registered": tasks.get("dashboard_watchdog_registered", False),
        "supervisor_watchdog_state": tasks.get("watchdog_state"),
        "dashboard_watchdog_state": tasks.get("dashboard_watchdog_state"),
        "elevated_helper": r"C:\sai-auth-doofus\scripts\doofus_register_watchdog_task_elevated.ps1",
        "last": last,
    }
