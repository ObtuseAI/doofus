"""Live lineage charts — plot lines only."""
from __future__ import annotations
from doofus.dashboard.live_chart_helpers import plot_from_rows, assert_plot_chart
from doofus.dashboard.live_data_api import get_candidate_lineage_rows

def build_lineage_charts() -> dict:
    rows = get_candidate_lineage_rows()
    depth: dict = {}
    for r in rows:
        g = r.get("generation", 0)
        depth[g] = depth.get(g, 0) + 1
    dr = [{"generation": k, "count": v} for k, v in sorted(depth.items())]
    charts = {"lineage_depth": plot_from_rows("Lineage depth by generation", dr, "generation", "count")}
    for name, fig in charts.items():
        assert_plot_chart(fig, name)
    return charts
