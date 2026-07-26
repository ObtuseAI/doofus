"""Live dashboard panel."""
from __future__ import annotations
from doofus.dashboard.live_data_api import get_model_auth_status, get_budget_rate_status, get_model_call_timeseries

def build_model_status_panel() -> dict:
    return {'auth': get_model_auth_status(), 'budget': get_budget_rate_status(), 'recent_calls': get_model_call_timeseries()[:10]}
