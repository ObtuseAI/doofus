"""Tests for recursive meta-supervisor."""
from __future__ import annotations

import json

import pytest

from doofus.meta import recursive_supervisor as rs


@pytest.fixture(autouse=True)
def isolated_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "META_STATE_FILE", tmp_path / "meta_state.json")
    monkeypatch.setenv("DOOFUS_META_EVOLUTION_MODE", "1")
    monkeypatch.setenv("DOOFUS_GEPA_BATCH_EVERY", "1")
    monkeypatch.setenv("DOOFUS_MAP_ELITES_MAINTAIN_EVERY", "1")
    monkeypatch.setenv("DOOFUS_CODEEVOLVE_EVERY", "999")
    yield


def test_meta_state_persistence():
    state = rs._load_meta_state()
    state["cycle_count"] = 5
    rs._save_meta_state(state)
    assert rs._load_meta_state()["cycle_count"] == 5


def test_should_run_gepa():
    state = {"cycle_count": 10, "last_gepa_cycle": 5}
    assert rs.should_run_gepa(state) is True


def test_run_meta_cycle_dry_run(monkeypatch):
    monkeypatch.setattr(rs, "run_one_cycle", lambda **kw: {"classification": "OK", "generation": 1, "promoted": 0})
    monkeypatch.setattr("doofus.safety.on_off_switch.check_may_proceed", lambda: (False, "test"))
    r = rs.run_meta_cycle(dry_run=True, live_model_if_available=False)
    assert "meta" in r


def test_run_meta_cycle_skips_meta_tasks_on_timeout(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        rs,
        "run_one_cycle",
        lambda **kw: {"classification": "DOOFUS_CYCLE_TIMEOUT", "generation": 1637, "promoted": 0},
    )
    monkeypatch.setattr(rs, "run_gepa_batch", lambda: calls.append("gepa") or {})
    monkeypatch.setattr(rs, "maintain_map_elites", lambda: calls.append("map") or {})
    result = rs.run_meta_cycle(dry_run=False, live_model_if_available=True)
    assert result["classification"] == "DOOFUS_CYCLE_TIMEOUT"
    assert calls == []
    assert result["meta"]["state"].get("cycle_count", 0) == 0
