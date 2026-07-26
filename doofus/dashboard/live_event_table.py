"""Live event tables."""
from __future__ import annotations
from doofus.dashboard.live_data_api import (
    get_cycle_timeseries, get_recent_candidates, get_recent_rejections,
    get_recent_promotions, get_model_call_timeseries, get_safety_events,
)
from doofus.dashboard import live_metric_queries as mq

def build_event_tables() -> dict:
    return {
        "cycles": get_cycle_timeseries()[:30],
        "candidates": get_recent_candidates()[:30],
        "rejections": get_recent_rejections()[:30],
        "promotions": get_recent_promotions()[:30],
        "model_calls": get_model_call_timeseries()[:30],
        "safety_events": get_safety_events()[:30],
        "dashboard_events": mq.recent_dashboard_events(30),
        "heartbeats": mq.recent_heartbeats(30),
        "metacognitive_events": mq.metacognitive_events(30),
    }
