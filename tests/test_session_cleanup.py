"""Tests for post-session cleanup."""
from doofus.runtime.session_cleanup import cleanup_after_autopilot_session


def test_session_cleanup_dry_run():
    r = cleanup_after_autopilot_session(dry_run=True)
    assert r["classification"] == "SESSION_CLEANUP_OK"
    assert r["dry_run"] is True
    assert isinstance(r["killed"], list)
    assert isinstance(r["skipped"], list)
