"""Live arena charts — plot lines only."""
from __future__ import annotations
from doofus.dashboard.live_chart_helpers import plot_from_rows, assert_plot_chart
from doofus.dashboard.live_data_api import get_arena_result_matrix
from doofus.arenas.arena_result_schema import parse_result_string

def build_arena_charts() -> dict:
    ar = get_arena_result_matrix()
    counts: dict = {}
    score_sums: dict = {}
    score_n: dict = {}
    for r in ar:
        k = r.get("arena", "unknown")
        counts[k] = counts.get(k, 0) + 1
        score = r.get("score")
        if score is None:
            _, score = parse_result_string(r.get("result", ""))
        score_sums[k] = score_sums.get(k, 0.0) + float(score or 0)
        score_n[k] = score_n.get(k, 0) + 1
    rows = [{"arena": k, "count": v} for k, v in counts.items()]
    score_rows = [{"arena": k, "avg_score": round(score_sums[k] / max(score_n[k], 1), 4)} for k in counts]
    charts = {
        "arena_counts": plot_from_rows("Arena result counts", rows, "arena", "count"),
        "arena_avg_scores": plot_from_rows("Arena average scores", score_rows or [{"arena": "none", "avg_score": 0}], "arena", "avg_score"),
    }
    for name, fig in charts.items():
        assert_plot_chart(fig, name)
    return charts
