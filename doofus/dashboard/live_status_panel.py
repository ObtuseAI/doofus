"""Live dashboard panel."""
from __future__ import annotations
from doofus.dashboard.live_data_api import get_status_cards, get_live_counters, get_heartbeat_status

def build_status_panel() -> dict:
    return {'cards': get_status_cards(), 'counters': get_live_counters(), 'heartbeat': get_heartbeat_status()}
