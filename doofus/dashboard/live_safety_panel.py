"""Live dashboard panel."""
from __future__ import annotations
from doofus.dashboard.live_data_api import get_safety_events, get_rejection_reason_counts

def build_safety_panel() -> dict:
    return {'events': get_safety_events(), 'rejection_reasons': get_rejection_reason_counts()}
