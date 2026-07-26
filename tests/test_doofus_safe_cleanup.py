"""Tests for runtime health and safe cleanup contract."""
from doofus.runtime.heartbeat_contract import classify_heartbeat_age
from doofus.runtime.safe_cleanup import run_safe_cleanup


def test_heartbeat_fresh():
    assert classify_heartbeat_age(30.0)["fresh"] is True


def test_heartbeat_stale():
    assert classify_heartbeat_age(200.0)["stale"] is True


def test_safe_cleanup_dry_run():
    r = run_safe_cleanup(dry_run=True)
    assert r["classification"] == "SAFE_CLEANUP_OK"
    assert r["dry_run"] is True
