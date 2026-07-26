"""SOTA dashboard chart tests."""
from __future__ import annotations

import pytest

from doofus.dashboard.live_map_elites_charts import build_map_elites_charts
from doofus.dashboard.live_gepa_trace_charts import build_gepa_trace_charts
from doofus.dashboard.live_gep_charts import build_gep_charts
from doofus.dashboard.meta_evolution_panel import get_meta_evolution_panel


def test_map_elites_charts_build():
    charts = build_map_elites_charts()
    assert "map_elites.map_elites_fitness" not in charts
    assert "map_elites_fitness" in charts


def test_gepa_charts_build():
    charts = build_gepa_trace_charts()
    assert "gepa_score_delta" in charts


def test_gep_charts_build():
    charts = build_gep_charts()
    assert "gep_capsule_fitness" in charts


def test_meta_evolution_panel_no_secrets():
    panel = get_meta_evolution_panel()
    text = str(panel).lower()
    assert "api_key" not in text
    assert "sk-" not in text
    assert panel["classification"] == "META_EVOLUTION_PANEL"
