"""GEP gene/capsule dashboard charts."""
from __future__ import annotations

from doofus.dashboard.live_chart_helpers import plot_from_rows, assert_plot_chart
from doofus.meta.gep.capsule_store import get_snapshot


def build_gep_charts() -> dict:
    snap = get_snapshot()
    caps = snap.get("top_capsules") or []
    rows = [{"capsule": c.get("capsule_id", "?")[:12], "fitness": float(c.get("fitness") or 0)} for c in caps]
    reuse_rows = [{"capsule": c.get("capsule_id", "?")[:12], "reuses": int(c.get("reuse_count") or 0)} for c in caps]
    charts = {
        "gep_capsule_fitness": plot_from_rows("GEP capsule fitness", rows or [{"capsule": "none", "fitness": 0}], "capsule", "fitness"),
        "gep_capsule_reuse": plot_from_rows("GEP capsule reuse", reuse_rows or [{"capsule": "none", "reuses": 0}], "capsule", "reuses"),
    }
    for name, fig in charts.items():
        assert_plot_chart(fig, name)
    return charts
