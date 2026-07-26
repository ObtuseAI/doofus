"""Tests for dashboard evolution panels."""
from doofus.dashboard.evolution_pressure_panel import get_evolution_pressure_panel
from doofus.dashboard.promotion_quality_panel import get_promotion_quality_panel


def test_evolution_panel_keys():
    p = get_evolution_pressure_panel()
    assert "pressure_level" in p


def test_promotion_quality_panel():
    p = get_promotion_quality_panel()
    assert p["promotion_threshold"] == 0.72
    assert p["proof_density_gate"]["active"] is True
