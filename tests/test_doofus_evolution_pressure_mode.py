"""Tests for evolution pressure mode."""
from doofus.evolution.adaptive_mutation_pressure import record_cycle, candidate_count_for_cycle
from doofus.evolution.best_ever_ledger import update_best_ever, get_best_ever
from doofus.evolution.evolution_policy import evolution_pressure_enabled


def test_evolution_pressure_enabled_default():
    assert evolution_pressure_enabled() is True


def test_stagnation_increases_candidate_count(tmp_path, monkeypatch):
    monkeypatch.setattr("doofus.evolution.adaptive_mutation_pressure.STATE_FILE", tmp_path / "p.json")
    for _ in range(6):
        record_cycle(generation=1, promoted=0)
    assert candidate_count_for_cycle() >= 3


def test_best_ever_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr("doofus.evolution.best_ever_ledger.LEDGER", tmp_path / "b.json")
    update_best_ever("c1", 0.8, 1)
    update_best_ever("c2", 0.9, 2)
    assert get_best_ever()["best_candidate_id"] == "c2"
