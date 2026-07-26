"""Live recursive learning charts."""
from __future__ import annotations
from doofus.dashboard.live_chart_helpers import plot_from_rows, plot_multi_from_rows, assert_plot_chart
from doofus.dashboard import live_metric_queries as mq

def build_recursive_learning_charts() -> dict:
    ts = mq.candidate_score_timeseries()
    g = mq.score_by_generation()
    charts = {
        "recursive_trajectory": plot_from_rows("Recursive learning per candidate", ts, "created_at", "score_recursive_learning"),
        "recursive_by_generation": plot_from_rows("Avg recursive learning by generation", g, "generation", "avg_recursive"),
        "recursive_vs_generalization": plot_multi_from_rows(
            "Recursive vs generalization",
            ts,
            "created_at",
            [("recursive", "score_recursive_learning"), ("generalization", "score_generalization")],
        ),
    }
    for name, fig in charts.items():
        assert_plot_chart(fig, name)
    return charts
