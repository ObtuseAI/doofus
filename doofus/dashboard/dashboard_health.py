"""Dashboard health classification — task state vs UI reachability."""
from __future__ import annotations

def dashboard_reachable(host: str = "127.0.0.1", port: int = 8765, timeout: float = 2.0) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def classify_dashboard_health(task_state: str | None) -> dict:
    state = (task_state or "unknown").strip()
    reachable = dashboard_reachable()
    bind_host = "127.0.0.1"

    if state == "Running" and reachable:
        classification = "task_running_ui_alive"
        needs_restart = False
    elif state == "Ready" and reachable:
        classification = "task_ready_ui_alive"
        needs_restart = False
    elif state == "Ready" and not reachable:
        classification = "task_ready_ui_dead"
        needs_restart = True
    elif state in ("Disabled", "unknown", "Stopped") and not reachable:
        classification = "task_stopped_ui_dead"
        needs_restart = True
    else:
        classification = "task_stopped_ui_dead" if not reachable else "task_running_ui_alive"
        needs_restart = not reachable

    return {
        "classification": classification,
        "task_state": state,
        "reachable": reachable,
        "bind_host": bind_host,
        "public_bind": False,
        "needs_restart": needs_restart,
        "persistent": classification in ("task_running_ui_alive", "task_ready_ui_alive") and reachable,
    }
