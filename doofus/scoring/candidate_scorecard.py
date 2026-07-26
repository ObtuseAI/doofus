"""Build auditable scorecard for promotion gate."""
from __future__ import annotations

from doofus.scoring.score_reconciler import reconcile_scores
from doofus.proof.proof_density_calculator import calculate_proof_density
from doofus.proof.lineage_proof_builder import build_lineage_proof


def build_scorecard(candidate: dict, scores: dict, *, arena_results: list[dict] | None = None) -> dict:
    scores = reconcile_scores(candidate, scores)
    arena_results = arena_results or []
    lin = build_lineage_proof(candidate, scores)
    density = calculate_proof_density(
        candidate, scores, arena_results=arena_results, lineage_delta=lin.get("lineage_delta"),
    )
    scores = dict(scores)
    scores["proof_density_score"] = density["proof_density_score"]
    return {
        "scores": scores,
        "proof_density": density,
        "lineage": lin,
        "arena_count": len(arena_results),
    }
