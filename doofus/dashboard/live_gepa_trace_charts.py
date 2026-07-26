"""GEPA trace dashboard charts."""
from __future__ import annotations

from doofus.dashboard.live_chart_helpers import plot_from_rows, assert_plot_chart
from doofus.meta.gepa.trace_collector import sample_traces
from doofus.meta.gepa.prompt_store import list_versions


def build_gepa_trace_charts() -> dict:
    traces = sample_traces(limit=50)
    rows = [{"idx": i, "score_delta": float(t.get("score_delta") or 0)} for i, t in enumerate(traces)]
    versions = list_versions("mutation")
    vrows = [{"version": v.get("version", i), "fitness": float(v.get("fitness") or 0)} for i, v in enumerate(versions)]
    charts = {
        "gepa_score_delta": plot_from_rows("GEPA score delta per trace", rows, "idx", "score_delta"),
        "gepa_prompt_fitness": plot_from_rows("GEPA prompt version fitness", vrows or [{"version": 0, "fitness": 0}], "version", "fitness"),
    }
    for name, fig in charts.items():
        assert_plot_chart(fig, name)
    return charts
