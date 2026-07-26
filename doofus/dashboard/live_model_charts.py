"""Live model charts — cost and call series."""
from __future__ import annotations
from doofus.dashboard.live_chart_helpers import plot_from_rows, plot_multi_from_rows, assert_plot_chart
from doofus.dashboard.live_data_api import get_model_auth_status
from doofus.dashboard import live_metric_queries as mq

def build_model_charts() -> dict:
    cost = mq.model_call_cost_series()
    calls = mq.model_calls_timeseries()
    charts = {
        "model_call_cost": plot_from_rows("Estimated cost per call", cost, "id", "cost_est"),
        "cumulative_cost": plot_from_rows("Cumulative estimated cost", cost, "id", "cumulative_cost"),
        "tokens_per_call": plot_from_rows("Tokens per call", calls, "id", "tokens_est"),
        "calls_by_provider": plot_from_rows("Calls by id (provider in tooltip)", calls, "id", "tokens_est"),
    }
    for name, fig in charts.items():
        assert_plot_chart(fig, name)
    charts["auth_note"] = get_model_auth_status()
    return charts
