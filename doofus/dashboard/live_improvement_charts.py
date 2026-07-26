"""Live improvement charts — cumulative promotion/rejection curves."""
from __future__ import annotations
from doofus.dashboard.live_chart_helpers import plot_from_rows, assert_plot_chart
from doofus.dashboard import live_metric_queries as mq

def build_improvement_charts() -> dict:
    prom = mq.cumulative_promotions()
    rej = mq.cumulative_rejections()
    gens = mq.score_by_generation()
    charts = {
        "cumulative_promotions": plot_from_rows("Cumulative promotions", prom, "id", "cumulative"),
        "cumulative_rejections": plot_from_rows("Cumulative rejections", rej, "id", "cumulative"),
        "best_score_trend": plot_from_rows("Best score by generation", gens, "generation", "best_total"),
        "avg_score_trend": plot_from_rows("Average score by generation", gens, "generation", "avg_total"),
    }
    for name, fig in charts.items():
        assert_plot_chart(fig, name)
    return charts
