"""Tests for GEP schema and capsule store."""
from __future__ import annotations

import pytest

from doofus.meta.gep.gep_schema import Gene, Capsule, EvolutionEvent
from doofus.meta.gep.gene_library import trait_to_gene, genes_to_traits
from doofus.meta.gep import capsule_store as cs
from doofus.meta.gep import event_emitter as ee


@pytest.fixture(autouse=True)
def isolated_gep(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CAPSULES_FILE", tmp_path / "capsules.json")
    monkeypatch.setattr(ee, "EVENTS_FILE", tmp_path / "events.jsonl")
    yield


def test_gene_roundtrip():
    g = trait_to_gene("replay_stability", 0.8)
    assert genes_to_traits([g]) == ["replay_stability"]


def test_capsule_create():
    cap = cs.create_capsule_from_candidate(
        {"candidate_id": "C1", "traits": ["replay_stability", "proof_density"], "mutation_type": "trait_mutation"},
        0.85,
    )
    assert cap.capsule_id.startswith("CAP_")


def test_event_emit():
    evt = ee.emit("test_event", {"foo": "bar"})
    assert evt.event_type == "test_event"
    assert ee.recent_events(1)
