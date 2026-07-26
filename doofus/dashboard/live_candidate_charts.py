"""Live candidate charts — per-candidate score trajectories."""
from __future__ import annotations
from doofus.dashboard.live_chart_helpers import plot_from_rows, plot_multi_from_rows, assert_plot_chart
from doofus.dashboard import live_metric_queries as mq

def build_candidate_charts() -> dict:
    ts = mq.candidate_score_timeseries()
    xs = [r.get("created_at", r.get("rowid", i)) for i, r in enumerate(ts)]
    charts = {
        "score_trajectory": plot_from_rows("Candidate score trajectory", ts, "created_at", "score_total"),
        "top_scores": plot_from_rows("Top candidates by score", mq.top_candidates(20), "candidate_id", "score_total"),
        "best_by_gen": plot_from_rows("Best score by generation", mq.score_by_generation(), "generation", "best_total"),
        "multi_scores": plot_multi_from_rows(
            "All score dimensions over candidates",
            ts,
            "created_at",
            [
                ("total", "score_total"),
                ("compounding", "score_compounding"),
                ("recursive", "score_recursive_learning"),
                ("generalization", "score_generalization"),
                ("replay", "score_replay"),
            ],
        ),
    }
    for name, fig in charts.items():
        assert_plot_chart(fig, name)
    return charts
