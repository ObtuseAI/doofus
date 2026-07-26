"""Tests for windows runtime manager."""
from doofus.runtime.windows_runtime_manager import run_once


def test_runtime_manager_once():
    r = run_once()
    assert r["classification"] == "RUNTIME_MANAGER_TICK"
    assert "health" in r
