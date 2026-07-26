"""Tests for burn-in metrics snapshot."""
from doofus.reports.burn_in_metrics_snapshot import capture_metrics_snapshot


def test_capture_metrics_snapshot_keys():
    snap = capture_metrics_snapshot(label="test")
    for key in ("git_head", "candidate_count", "promotion_count", "dashboard_host"):
        assert key in snap
    assert snap["dashboard_host"] == "127.0.0.1"
