"""Tests for elite archive."""
from doofus.evolution.elite_archive import add_elite, get_elite_archive, load_elite_parents, pin_best_ever


def test_add_elite_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr("doofus.evolution.elite_archive.ARCHIVE", tmp_path / "elite.json")
    monkeypatch.setattr("doofus.evolution.elite_archive.USAGE", tmp_path / "usage.json")
    add_elite({"candidate_id": "A", "parent_id": "P1", "mutation_type": "m1", "traits": ["x"]}, 0.85)
    add_elite({"candidate_id": "B", "parent_id": "P2", "mutation_type": "m2", "traits": ["y"]}, 0.90)
    archive = get_elite_archive()
    assert archive["elite_archive_count"] >= 2
    parents = load_elite_parents(limit=5)
    assert len(parents) >= 2
