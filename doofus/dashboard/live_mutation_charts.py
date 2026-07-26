"""Live mutation/variant charts — time-series plot lines."""
from __future__ import annotations
from doofus.dashboard.live_chart_helpers import plot_from_rows, plot_multi_from_rows, assert_plot_chart
from doofus.dashboard import live_metric_queries as mq

def build_mutation_charts() -> dict:
    gens = mq.candidates_per_generation()
    muts = mq.mutation_type_counts()
    status = mq.candidate_status_counts()
    score_g = mq.score_by_generation()
    charts = {
        "candidates_by_generation": plot_from_rows("Candidates by generation", gens, "generation", "count"),
        "mutation_types": plot_from_rows("Mutation type counts", muts, "mutation_type", "count"),
        "status_distribution": plot_from_rows("Candidate status", status, "status", "count"),
        "score_components_by_gen": plot_multi_from_rows(
            "Score components by generation",
            score_g,
            "generation",
            [
                ("avg total", "avg_total"),
                ("avg replay", "avg_replay"),
                ("avg safety", "avg_safety"),
                ("avg generalization", "avg_generalization"),
            ],
        ),
    }
    for name, fig in charts.items():
        assert_plot_chart(fig, name)
    return charts
