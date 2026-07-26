from __future__ import annotations

from doofus.experiments.evolution_vs_baseline import run_experiment


def test_evolution_experiment_freezes_candidate_before_heldout() -> None:
    report = run_experiment(generations=2, engine_ref="test")
    assert report["registered_target"] == "heldout-toy-optimizer"
    assert report["candidate"]["frozen_before_heldout"] is True
    assert len(report["candidate"]["sha256"]) == 64
    assert report["heldout"]["isolation_verified"] is True
    assert report["heldout"]["baseline"]["task_count"] == 7
    assert report["heldout"]["candidate"]["task_count"] == 7
    assert report["evolution"]["classification"] == "EVOLVE_PROJECT_COMPLETE"
