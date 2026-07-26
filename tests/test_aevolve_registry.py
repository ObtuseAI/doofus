"""Tests for A-Evolve algorithm registry."""
from __future__ import annotations

import pytest

from doofus.meta.aevolve import algorithm_selector as sel
from doofus.meta.aevolve.stagnation_escalator import escalate


@pytest.fixture(autouse=True)
def isolated_aevolve(tmp_path, monkeypatch):
    monkeypatch.setattr(sel, "STATS_FILE", tmp_path / "stats.json")
    monkeypatch.setenv("DOOFUS_AEVOLVE_MODE", "1")
    yield


def test_select_algorithms():
    algos = sel.select_algorithms_for_cycle(5, seed=42)
    assert len(algos) == 5
    assert all(isinstance(a, str) for a in algos)


def test_record_outcome_updates_stats():
    sel.record_outcome("trait_shuffle", promoted=True)
    sel.record_outcome("trait_shuffle", promoted=False)
    snap = sel.get_snapshot()
    assert snap["stats"]["trait_shuffle"]["trials"] == 2


def test_stagnation_escalation():
    r = escalate(12)
    assert r["escalated"] is True
