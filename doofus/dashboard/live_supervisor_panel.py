"""Live dashboard panel."""
from __future__ import annotations
from doofus.dashboard.live_data_api import get_task_status, get_heartbeat_status, get_checkpoint_status

def build_supervisor_panel() -> dict:
    return {'tasks': get_task_status(), 'heartbeat': get_heartbeat_status(), 'checkpoint': get_checkpoint_status()}
