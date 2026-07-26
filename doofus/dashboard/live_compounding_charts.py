"""Live compounding charts."""
from __future__ import annotations
from doofus.dashboard.live_chart_helpers import plot_from_rows, plot_multi_from_rows, assert_plot_chart
from doofus.dashboard import live_metric_queries as mq

def build_compounding_charts() -> dict:
    ts = mq.candidate_score_timeseries()
    g = mq.score_by_generation()
    charts = {
        "compounding_trajectory": plot_from_rows("Compounding score per candidate", ts, "created_at", "score_compounding"),
        "compounding_by_generation": plot_from_rows("Avg compounding by generation", g, "generation", "avg_compounding"),
        "compounding_vs_total": plot_multi_from_rows(
            "Compounding vs total score",
            ts,
            "created_at",
            [("compounding", "score_compounding"), ("total", "score_total")],
        ),
    }
    for name, fig in charts.items():
        assert_plot_chart(fig, name)
    return charts
