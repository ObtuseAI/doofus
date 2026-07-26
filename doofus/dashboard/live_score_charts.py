"""Live score charts — multi-series sharp plots."""
from __future__ import annotations
from doofus.dashboard.live_chart_helpers import plot_from_rows, plot_multi_from_rows, assert_plot_chart
from doofus.dashboard import live_metric_queries as mq

def build_score_charts() -> dict:
    g = mq.score_by_generation()
    ts = mq.candidate_score_timeseries()
    charts = {
        "avg_score": plot_from_rows("Average score by generation", g, "generation", "avg_total"),
        "best_score": plot_from_rows("Best score by generation", g, "generation", "best_total"),
        "score_components_gen": plot_multi_from_rows(
            "Score components by generation",
            g,
            "generation",
            [
                ("safety", "avg_safety"),
                ("replay", "avg_replay"),
                ("generalization", "avg_generalization"),
                ("compounding", "avg_compounding"),
                ("recursive", "avg_recursive"),
            ],
        ),
        "live_score_trajectory": plot_from_rows("Live candidate score trajectory", ts, "created_at", "score_total"),
    }
    for name, fig in charts.items():
        assert_plot_chart(fig, name)
    return charts
