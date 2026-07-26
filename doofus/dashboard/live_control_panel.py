"""Live dashboard panel."""
from __future__ import annotations
from doofus.dashboard.live_data_api import read_control_state

def build_control_panel() -> dict:
    return {'switch': read_control_state(), 'writes_files_only': True}
