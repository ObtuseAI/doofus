"""MAP-Elites dashboard charts."""
from __future__ import annotations

from doofus.dashboard.live_chart_helpers import plot_from_rows, assert_plot_chart
from doofus.evolution.map_elites_archive import load_all, occupancy_rate


def build_map_elites_charts() -> dict:
    cells = load_all()
    rows = [{"cell": c.get("cell_key", "?"), "fitness": float(c.get("fitness") or 0)} for c in cells]
    if not rows:
        rows = [{"cell": "empty", "fitness": 0.0}]
    charts = {"map_elites_fitness": plot_from_rows(f"MAP-Elites fitness (occ {occupancy_rate():.1%})", rows, "cell", "fitness")}
    for name, fig in charts.items():
        assert_plot_chart(fig, name)
    return charts
