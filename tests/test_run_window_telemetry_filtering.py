"""Tests for run-window telemetry filtering in live verification finalization."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from doofus.reports.run_window_telemetry_filter import (
    RunWindowFilterResult,
    classify_init_watchdog,
    event_in_window,
    filter_events_by_run_window,
    normalize_run_bounds,
    stale_classification_impact,
)


def _ts(base: datetime, offset_seconds: int) -> str:
    return (base + timedelta(seconds=offset_seconds)).astimezone(timezone.utc).isoformat()


def test_stale_retry2_init_timeout_excluded_from_retry3_finalization():
    run_start = datetime(2026, 7, 5, 18, 52, 31, tzinfo=timezone.utc)
    run_end = datetime(2026, 7, 5, 18, 55, 48, tzinfo=timezone.utc)
    stale = {
        "timestamp": "2026-07-05T15:55:50+00:00",
        "generation": 1640,
        "step": "cycle_init_timeout",
        "duration_ms": 180000.0,
    }
    current = {
        "timestamp": "2026-07-05T18:52:38+00:00",
        "generation": 1640,
        "step": "cycle_init_provider_gate_end",
        "status": "ok",
    }
    result = filter_events_by_run_window(
        [stale, current],
        generation=1640,
        window_start=run_start,
        window_end=run_end,
        source_name="cycle_init_events.jsonl",
    )
    assert stale not in result.events_in_window
    assert current in result.events_in_window
    assert result.events_excluded_count >= 1


def test_current_inline_rescue_ok_included():
    run_start = datetime(2026, 7, 5, 18, 52, 31, tzinfo=timezone.utc)
    run_end = datetime(2026, 7, 5, 18, 55, 48, tzinfo=timezone.utc)
    event = {
        "timestamp_utc": "2026-07-05T18:54:10+00:00",
        "generation": 1640,
        "event_type": "end",
        "status": "ok",
    }
    result = filter_events_by_run_window(
        [event],
        generation=1640,
        window_start=run_start,
        window_end=run_end,
        source_name="inline_rescue_events.jsonl",
    )
    assert event in result.events_in_window


def test_stale_init_watchdog_does_not_override_current_ok():
    run_start = datetime(2026, 7, 5, 18, 52, 31, tzinfo=timezone.utc)
    run_end = datetime(2026, 7, 5, 18, 55, 48, tzinfo=timezone.utc)
    events = [
        {"timestamp": "2026-07-05T15:55:50+00:00", "generation": 1640, "step": "cycle_init_timeout"},
        {"timestamp": "2026-07-05T18:52:38+00:00", "generation": 1640, "step": "cycle_init_end", "duration_ms": 5000.0},
    ]
    filtered = filter_events_by_run_window(
        events,
        generation=1640,
        window_start=run_start,
        window_end=run_end,
    )
    timed_out, status, _, _ = classify_init_watchdog(filtered.events_in_window)
    assert timed_out is False
    assert status == "ok"


def test_stale_shadow_upgrade_stall_does_not_override_current_deferral():
    run_start = datetime(2026, 7, 5, 18, 52, 31, tzinfo=timezone.utc)
    run_end = datetime(2026, 7, 5, 18, 55, 48, tzinfo=timezone.utc)
    stale = {"timestamp": "2026-07-05T17:47:44+00:00", "generation": 1640, "step": "shadow_upgrade_item_timeout"}
    current = {"timestamp": "2026-07-05T18:52:41+00:00", "generation": 1640, "step": "shadow_upgrade_deferred"}
    result = filter_events_by_run_window(
        [stale, current],
        generation=1640,
        window_start=run_start,
        window_end=run_end,
        source_name="shadow_upgrade_events.jsonl",
    )
    assert current in result.events_in_window
    assert stale not in result.events_in_window


def test_stale_high_score_miner_timeout_does_not_override_current_ok():
    run_start = datetime(2026, 7, 5, 18, 52, 31, tzinfo=timezone.utc)
    run_end = datetime(2026, 7, 5, 18, 55, 48, tzinfo=timezone.utc)
    stale = {"timestamp": "2026-07-05T15:55:50+00:00", "generation": 1640, "step": "high_score_miner_deadline_exceeded"}
    current = {"timestamp": "2026-07-05T18:52:41+00:00", "generation": 1640, "step": "high_score_miner_query_end", "rows_returned": 20}
    result = filter_events_by_run_window(
        [stale, current],
        generation=1640,
        window_start=run_start,
        window_end=run_end,
    )
    assert current in result.events_in_window


def test_stale_provider_gate_outside_window_excluded():
    run_start = datetime(2026, 7, 5, 18, 52, 31, tzinfo=timezone.utc)
    run_end = datetime(2026, 7, 5, 18, 55, 48, tzinfo=timezone.utc)
    stale = {"timestamp": "2026-07-05T15:55:50+00:00", "generation": 1640, "step": "cycle_init_provider_gate_end"}
    current = {"timestamp": "2026-07-05T18:52:38+00:00", "generation": 1640, "step": "cycle_init_provider_gate_end"}
    result = filter_events_by_run_window([stale, current], generation=1640, window_start=run_start, window_end=run_end)
    assert len(result.events_in_window) == 1
    assert result.events_in_window[0] is current


def test_stale_event_counts_reported():
    run_start = datetime(2026, 7, 5, 18, 52, 31, tzinfo=timezone.utc)
    run_end = datetime(2026, 7, 5, 18, 55, 48, tzinfo=timezone.utc)
    events = [
        {"timestamp": "2026-07-05T15:55:50+00:00", "generation": 1640, "step": "cycle_init_timeout"},
        {"timestamp": "2026-07-05T18:52:38+00:00", "generation": 1640, "step": "cycle_init_end"},
    ]
    result = filter_events_by_run_window(
        events,
        generation=1640,
        window_start=run_start,
        window_end=run_end,
        source_name="cycle_init_events.jsonl",
    )
    assert result.events_excluded_count == 1
    assert result.stale_event_sources.get("cycle_init_events.jsonl") == 1


def test_classification_uses_only_in_window_events():
    run_start = datetime(2026, 7, 5, 18, 52, 31, tzinfo=timezone.utc)
    run_end = datetime(2026, 7, 5, 18, 55, 48, tzinfo=timezone.utc)
    all_events = [
        {"timestamp": "2026-07-05T15:55:50+00:00", "generation": 1640, "step": "cycle_init_timeout"},
        {"timestamp": "2026-07-05T18:52:38+00:00", "generation": 1640, "step": "cycle_init_end", "duration_ms": 1000.0},
    ]
    filtered = filter_events_by_run_window(all_events, generation=1640, window_start=run_start, window_end=run_end)
    impact = stale_classification_impact(
        unfiltered_init_events=all_events,
        filtered_init_events=filtered.events_in_window,
        generation=1640,
        pass_without_stale=True,
    )
    assert impact["classification_after_stale_filter"] == "DOOFUS_GEN1640_RETRY3_LIVE_VERIFICATION_PASS"
    assert impact["stale_events_changed_classification"] is True


def test_missing_run_window_fallback_is_bounded():
    run_start = datetime(2026, 7, 5, 18, 52, 31, tzinfo=timezone.utc)
    run_end = datetime(2026, 7, 5, 18, 55, 48, tzinfo=timezone.utc)
    events = [{"generation": 1640, "step": "cycle_init_end"} for _ in range(40)]
    result = filter_events_by_run_window(
        events,
        generation=1640,
        window_start=run_start,
        window_end=run_end,
        fallback_tail=30,
    )
    assert len(result.events_in_window) == 30


def test_timezone_aware_timestamps_filter_correctly():
    run_start = datetime(2026, 7, 5, 13, 52, 31, tzinfo=timezone(timedelta(hours=-5)))
    run_end = datetime(2026, 7, 5, 13, 55, 48, tzinfo=timezone(timedelta(hours=-5)))
    event = {"timestamp": "2026-07-05T18:52:38+00:00", "generation": 1640, "step": "ok"}
    result = filter_events_by_run_window([event], generation=1640, window_start=run_start, window_end=run_end)
    assert event in result.events_in_window


def test_process_log_bounds_honored():
    start = datetime(2026, 7, 5, 18, 52, 31, tzinfo=timezone.utc)
    end = datetime(2026, 7, 5, 18, 55, 48, tzinfo=timezone.utc)
    lo, hi = normalize_run_bounds(start, end)
    inside = {"timestamp": "2026-07-05T18:53:00+00:00", "generation": 1640}
    outside = {"timestamp": "2026-07-05T15:55:50+00:00", "generation": 1640}
    assert event_in_window(inside, window_start=lo, window_end=hi)
    assert not event_in_window(outside, window_start=lo, window_end=hi)


def test_run_id_preferred_over_timestamp_window():
    run_start = datetime(2026, 7, 5, 18, 52, 31, tzinfo=timezone.utc)
    run_end = datetime(2026, 7, 5, 18, 55, 48, tzinfo=timezone.utc)
    event = {"timestamp": "2026-01-01T00:00:00+00:00", "generation": 1640, "run_id": "retry3-run", "step": "ok"}
    result = filter_events_by_run_window(
        [event],
        generation=1640,
        window_start=run_start,
        window_end=run_end,
        run_id="retry3-run",
    )
    assert event in result.events_in_window


def test_multiple_retries_same_generation_separated_by_window():
    run_start = datetime(2026, 7, 5, 18, 52, 31, tzinfo=timezone.utc)
    run_end = datetime(2026, 7, 5, 18, 55, 48, tzinfo=timezone.utc)
    retry2 = {"timestamp": "2026-07-05T17:47:44+00:00", "generation": 1640, "step": "cycle_init_timeout"}
    retry3 = {"timestamp": "2026-07-05T18:52:38+00:00", "generation": 1640, "step": "cycle_init_end"}
    result = filter_events_by_run_window(
        [retry2, retry3],
        generation=1640,
        window_start=run_start,
        window_end=run_end,
    )
    assert retry3 in result.events_in_window
    assert retry2 in result.events_excluded_as_stale


def test_stale_events_changed_classification_recorded():
    all_events = [
        {"timestamp": "2026-07-05T15:55:50+00:00", "generation": 1640, "step": "cycle_init_timeout"},
        {"timestamp": "2026-07-05T18:52:38+00:00", "generation": 1640, "step": "cycle_init_end"},
    ]
    filtered = filter_events_by_run_window(
        all_events,
        generation=1640,
        window_start=datetime(2026, 7, 5, 18, 52, 31, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 5, 18, 55, 48, tzinfo=timezone.utc),
    )
    impact = stale_classification_impact(
        unfiltered_init_events=all_events,
        filtered_init_events=filtered.events_in_window,
        generation=1640,
        pass_without_stale=True,
    )
    assert impact["classification_before_stale_filter"].endswith("PARTIAL")
    assert impact["classification_after_stale_filter"].endswith("PASS")


def test_filter_result_summary_fields():
    result = RunWindowFilterResult(
        events_in_window=[{"step": "ok"}],
        events_excluded_as_stale=[],
        run_window_start="a",
        run_window_end="b",
        run_window_filter_applied=True,
        events_in_window_count=1,
        events_excluded_count=0,
    )
    summary = result.to_summary_fields()
    assert summary["run_window_filter_applied"] is True
    assert summary["events_in_window"] == 1
