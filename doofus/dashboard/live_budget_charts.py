"""Live budget charts — usage over call history."""
from __future__ import annotations
from doofus.dashboard.live_chart_helpers import plot_from_rows, assert_plot_chart
from doofus.dashboard.live_data_api import get_budget_rate_status
from doofus.dashboard import live_metric_queries as mq

def build_budget_charts() -> dict:
    cost = mq.model_call_cost_series()
    b = get_budget_rate_status()
    charts = {
        "cost_over_calls": plot_from_rows("Daily cost accumulation (est)", cost, "id", "cumulative_cost"),
        "hourly_calls": plot_from_rows("Model calls over time", mq.model_calls_timeseries(), "id", "tokens_est"),
        "budget_cap_line": plot_from_rows(
            "Budget context",
            [{"label": "spent", "value": float(b.get("daily_cost_est", 0))}, {"label": "cap", "value": float(b.get("max_daily_cost_usd", 5))}],
            "label",
            "value",
        ),
    }
    for name, fig in charts.items():
        assert_plot_chart(fig, name)
    return charts
