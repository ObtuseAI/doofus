"""Dashboard process guard — detect Ready vs running UI."""
from __future__ import annotations

from doofus.dashboard.dashboard_health import classify_dashboard_health, dashboard_reachable


def dashboard_persistence_status(task_state: str | None) -> dict:
    return classify_dashboard_health(task_state)
