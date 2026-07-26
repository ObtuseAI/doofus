"""Dashboard health panel."""
from __future__ import annotations

from doofus.dashboard.dashboard_health import classify_dashboard_health
from doofus.supervisor.scheduled_task_guard import get_scheduled_task_states
from doofus.safety.on_off_switch import status as switch_status


def get_dashboard_health_panel() -> dict:
    tasks = get_scheduled_task_states()
    health = classify_dashboard_health(tasks.get("dashboard_state"))
    return {"health": health, "tasks": tasks, "switch": switch_status()}


def health_panel() -> dict:
    """Backward-compatible alias."""
    return get_dashboard_health_panel()
