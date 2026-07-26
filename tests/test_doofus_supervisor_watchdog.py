"""Tests for supervisor watchdog."""
import os

from doofus.core import doofus_paths
from doofus.supervisor.heartbeat_watchdog import heartbeat_status
from doofus.supervisor.doofus_24_7_supervisor import run_supervisor
from doofus.supervisor.process_singleton import cleanup_stale_lock


def test_heartbeat_status_shape():
    r = heartbeat_status()
    assert "status" in r


def test_cleanup_stale_lock_missing():
    assert cleanup_stale_lock("nonexistent_test_lock") is True


def test_cleanup_stale_lock_dead_pid():
    path = doofus_paths.STATE / "stale_lock_case.pid"
    path.write_text("999999", encoding="utf-8")
    assert cleanup_stale_lock("stale_lock_case") is True
    assert not path.exists()


def test_cleanup_stale_lock_live_pid_preserved():
    path = doofus_paths.STATE / "live_lock_case.pid"
    path.write_text(str(os.getpid()), encoding="utf-8")
    assert cleanup_stale_lock("live_lock_case") is False
    assert path.exists()


def test_run_supervisor_stops_after_timeout_attempt(monkeypatch):
    calls = {"count": 0}
    monkeypatch.setattr("doofus.supervisor.doofus_24_7_supervisor.acquire_singleton", lambda _name: True)
    monkeypatch.setattr("doofus.supervisor.doofus_24_7_supervisor.release_singleton", lambda _name: None)
    monkeypatch.setattr("doofus.supervisor.doofus_24_7_supervisor.bootstrap_autonomous_runtime", lambda: None)
    monkeypatch.setattr("doofus.supervisor.doofus_24_7_supervisor.check_may_proceed", lambda: (True, "ok"))
    monkeypatch.setattr("doofus.supervisor.doofus_24_7_supervisor.emit_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr("doofus.supervisor.doofus_24_7_supervisor._sleep_with_heartbeat", lambda _s: None)

    def fake_run_meta_cycle(**_kwargs):
        calls["count"] += 1
        return {"classification": "DOOFUS_CYCLE_TIMEOUT"}

    monkeypatch.setattr("doofus.supervisor.doofus_24_7_supervisor.run_meta_cycle", fake_run_meta_cycle)
    assert run_supervisor(max_cycles=1) == 0
    assert calls["count"] == 1
