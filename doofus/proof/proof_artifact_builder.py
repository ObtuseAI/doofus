"""Orchestrate proof artifact building for one candidate."""
from __future__ import annotations

from doofus.proof.replay_proof_builder import build_replay_proof
from doofus.proof.arena_support_builder import build_arena_support
from doofus.proof.score_stability_builder import build_score_stability
from doofus.proof.lineage_proof_builder import build_lineage_proof
from doofus.proof.proof_density_calculator import calculate_proof_density


def build_proof_artifacts(candidate: dict, scores: dict, *, arena_results: list[dict] | None = None) -> dict:
    replay = build_replay_proof(candidate, scores)
    arena = build_arena_support(candidate, scores, arena_results)
    stability = build_score_stability(candidate, scores)
    lineage = build_lineage_proof(candidate, scores)
    density = calculate_proof_density(
        candidate, scores, arena_results=arena["arena_results"], lineage_delta=lineage.get("lineage_delta"),
    )
    scores = dict(scores)
    scores["proof_density_score"] = density["proof_density_score"]
    return {
        "replay": replay,
        "arena": arena,
        "stability": stability,
        "lineage": lineage,
        "proof_density": density,
        "updated_scores": scores,
        "arena_results": arena["arena_results"],
    }
