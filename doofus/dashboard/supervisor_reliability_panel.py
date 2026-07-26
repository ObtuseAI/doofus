"""Supervisor reliability dashboard panel."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import STATE
from doofus.supervisor.heartbeat_watchdog import heartbeat_status
from doofus.supervisor.scheduled_task_guard import get_scheduled_task_states
from doofus.supervisor.supervisor_watchdog import duplicate_pid_report


def get_supervisor_reliability_panel() -> dict:
    watch = {}
    p = STATE / "watchdog_last.json"
    if p.exists():
        watch = json.loads(p.read_text(encoding="utf-8"))
    return {
        "heartbeat": heartbeat_status(),
        "tasks": get_scheduled_task_states(),
        "duplicates": duplicate_pid_report(),
        "last_watchdog": watch.get("classification", "none"),
        "last_watchdog_actions": watch.get("actions", []),
    }
