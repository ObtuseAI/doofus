"""Evidence-based proof density — real artifacts only, no fake inflation."""
from __future__ import annotations

PROMOTION_THRESHOLD = 0.72


def calculate_proof_density(
    candidate: dict,
    scores: dict,
    *,
    arena_results: list[dict] | None = None,
    lineage_delta: float | None = None,
) -> dict:
    """Sum weighted evidence components; each counted once."""
    arena_results = arena_results or []
    components: dict[str, float] = {}
    traits = candidate.get("traits") or []
    if isinstance(traits, str):
        traits = [t.strip() for t in traits.split(",") if t.strip()]

    if float(scores.get("score_replay") or 0) >= 0.45:
        components["replay_pass"] = 0.15
    wins = sum(1 for r in arena_results if str(r.get("result", "")).lower().startswith("pass"))
    if wins > 0:
        components["arena_support"] = 0.15
    stab = float(scores.get("replay_stability_score") or scores.get("score_replay") or 0)
    if stab >= 0.55 or "replay_stability" in traits:
        components["score_stability"] = 0.10
    if float(scores.get("score_safety") or 0) >= 0.99:
        components["safety_pass"] = 0.15
    if float(scores.get("bloat_penalty") or 0) <= 0.20:
        components["bloat_pass"] = 0.10
    if candidate.get("parent_id") and lineage_delta is not None and lineage_delta > 0:
        components["lineage_improvement"] = 0.10
    elif candidate.get("parent_id"):
        components["lineage_present"] = 0.05
    if float(scores.get("score_total") or 0) > float(scores.get("_baseline") or 0.5):
        components["regression_pass"] = 0.10
    if "proof_density" in traits and float(scores.get("proof_density_score") or 0) >= 0.45:
        components["proof_trait_verified"] = 0.10

    total = round(min(1.0, sum(components.values())), 4)
    return {
        "proof_density_score": total,
        "proof_components": components,
        "component_count": len(components),
        "evidence_types": list(components.keys()),
    }
