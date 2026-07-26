"""Live safety charts — plot lines only."""
from __future__ import annotations
from doofus.dashboard.live_chart_helpers import plot_from_rows, assert_plot_chart
from doofus.dashboard.live_data_api import get_rejection_reason_counts, get_safety_events

def build_safety_charts() -> dict:
    events = get_safety_events()
    event_rows = [{"type": e.get("event_type"), "count": 1} for e in events]
    charts = {
        "rejection_reasons": plot_from_rows("Rejection reasons", get_rejection_reason_counts(), "reason", "count"),
        "safety_events": plot_from_rows("Safety events", event_rows, "type", "count"),
    }
    for name, fig in charts.items():
        assert_plot_chart(fig, name)
    return charts
