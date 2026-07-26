"""Shadow elite promotion criteria."""
from __future__ import annotations

from doofus.scoring.promotion_gate import PROMOTION_THRESHOLD, max_bloat_for_promotion
from doofus.evolution.shadow_elite_archive import add_shadow_elite, shadow_elite_enabled


def try_shadow_elite(candidate: dict, scores: dict, promo: dict) -> dict:
    if not shadow_elite_enabled():
        return {"shadow_elite": False}
    score_ok = (
        float(scores.get("score_total") or 0) >= PROMOTION_THRESHOLD
        and float(scores.get("score_safety") or 0) >= 0.99
        and float(scores.get("bloat_penalty") or 0) <= max_bloat_for_promotion()
        and not promo.get("promoted")
    )
    if not score_ok:
        return {"shadow_elite": False}
    proof = float(scores.get("proof_density_score") or 0)
    if promo.get("proof_density_passed") and promo.get("arena_support_passed") and promo.get("promoted"):
        return {"shadow_elite": False, "reason": "already_promotable"}
    result = add_shadow_elite(candidate, proof_density=proof, reason="under_proven_high_score")
    return {"shadow_elite": True, **result}
