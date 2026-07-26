"""Tests for SOTA KPI tracker."""
from __future__ import annotations

from doofus.reports.sota_kpi_tracker import build_hourly_report_markdown, capture_kpi_snapshot, champion_generation


def test_build_hourly_report_markdown():
    snap = {
        "captured_at": "2026-07-03T10:00:00+00:00",
        "since_generation": 1633,
        "checkpoint": {"generation": 1633, "baseline_score": 0.9378},
        "composer_mutations": {"attempts": 5, "success_rate": 0.8, "live_calls": 4, "successful_mutations": 3},
        "fallback": {"fallback_events": 1, "fallback_rate": 0.2},
        "cost_per_promotion": {"cost_per_promotion_usd": 0.05, "total_model_cost_usd": 1.5},
        "promotion_replay_stability": {"promotions_count": 2, "avg_score_replay": 0.55},
        "champion_defense": {"checkpoint_baseline": 0.9378, "best_ever_score": 0.9392, "promotions_since_floor": 1},
        "map_elites_growth": {"sql_archive_cells": 11},
        "meta_cadence": {"meta_cycle_count": 1633, "cycles_until_gepa": 4},
        "metacognitive_calibration": {"sample_count": 40, "brier_score": 0.12, "brier_skill": 0.88},
        "sqlite_contention": {"probe_ok": True, "locked_events": 0},
    }
    md = build_hourly_report_markdown(snap, None)
    assert "Hourly KPI Report" in md
    assert "Composer mutation success" in md
    assert "Metacognitive calibration KPI" in md
    assert "0.12" in md


def test_capture_kpi_snapshot_shape():
    snap = capture_kpi_snapshot(since_gen=champion_generation())
    assert snap["classification"] == "DOOFUS_SOTA_KPI_SNAPSHOT"
    for key in (
        "composer_mutations",
        "fallback",
        "cost_per_promotion",
        "promotion_replay_stability",
        "champion_defense",
        "map_elites_growth",
        "meta_cadence",
        "metacognitive_calibration",
        "sqlite_contention",
        "baseline_certification",
    ):
        assert key in snap
