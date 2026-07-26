"""Tests for compounding acceleration helpers."""
import json
import random

from doofus.mutation.model_proposal_applier import apply_proposal_to_candidate
from doofus.evolution.compound_evolution import effective_promotion_baseline


def test_apply_model_proposal_traits():
    cand = {"candidate_id": "X", "traits": ["replay_stability"], "mutation_type": "trait_mutation"}
    proposal = {"proposals": [{"traits": ["proof_density", "compounding_bias"], "rationale": "test"}]}
    out = apply_proposal_to_candidate(cand, proposal, rng=random.Random(1))
    assert out["mutation_type"] == "model_guided_mutation"
    assert "proof_density" in out["traits"]


def test_apply_model_proposal_rejects_forbidden():
    cand = {"candidate_id": "X", "traits": ["replay_stability"], "mutation_type": "trait_mutation"}
    proposal = {"proposals": [{"traits": ["wanefall_mutation", "proof_density"]}]}
    out = apply_proposal_to_candidate(cand, proposal, rng=random.Random(1))
    assert "wanefall_mutation" not in out["traits"]
    assert "proof_density" in out["traits"]
    assert out["mutation_type"] == "model_guided_mutation"


def test_effective_promotion_baseline_stagnation(tmp_path, monkeypatch):
    from doofus.core import doofus_paths
    from doofus.evolution import adaptive_mutation_pressure as amp
    from doofus.evolution import best_ever_ledger as bel

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(doofus_paths, "STATE", state)
    monkeypatch.setattr(amp, "STATE_FILE", state / "evolution_pressure_state.json")
    monkeypatch.setattr(bel, "LEDGER", state / "best_ever_ledger.json")
    monkeypatch.setenv("DOOFUS_STAGNATION_CYCLES_FOR_SLACK", "10")
    monkeypatch.setenv("DOOFUS_STAGNATION_PROMOTION_SLACK", "0.015")

    (state / "evolution_pressure_state.json").write_text(
        json.dumps({"stagnation_cycles": 50, "pressure_level": 3.0}), encoding="utf-8"
    )
    (state / "best_ever_ledger.json").write_text(
        json.dumps({"best_score": 0.9269}), encoding="utf-8"
    )
    floor = effective_promotion_baseline(0.9217)
    assert floor < 0.9217
    assert floor <= 0.9269 * 0.99
