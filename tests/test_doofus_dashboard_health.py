"""Tests for dashboard health classification."""
from doofus.dashboard.dashboard_health import classify_dashboard_health


def test_task_ready_ui_dead(monkeypatch):
    monkeypatch.setattr("doofus.dashboard.dashboard_health.dashboard_reachable", lambda *a, **k: False)
    h = classify_dashboard_health("Ready")
    assert h["classification"] == "task_ready_ui_dead"
    assert h["needs_restart"] is True


def test_task_ready_ui_alive(monkeypatch):
    monkeypatch.setattr("doofus.dashboard.dashboard_health.dashboard_reachable", lambda *a, **k: True)
    h = classify_dashboard_health("Ready")
    assert h["classification"] == "task_ready_ui_alive"
    assert h["needs_restart"] is False
