"""Tests for 12-hour delta report."""
from doofus.evolution.evolution_quality_analyzer import analyze


def test_evolution_quality_analyze():
    r = analyze(since="2099-01-01T00:00:00+00:00")
    assert "verdict" in r
