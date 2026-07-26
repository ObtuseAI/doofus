"""Promotion gate — strict proof-gated promotion, no forced promotion."""
from __future__ import annotations

import os

from doofus.scoring.arena_support_gate import check_arena_support
from doofus.scoring.proof_density_gate import check_proof_density
from doofus.scoring.candidate_scorecard import build_scorecard
from doofus.config.proof_builder_runtime_config import evidence_based_proof_density
from doofus.meta.codeevolve.param_overrides import load_promotion_threshold

from doofus.evolution.compound_evolution import effective_promotion_baseline

PROMOTION_THRESHOLD = 0.72


def active_promotion_threshold() -> float:
    return load_promotion_threshold(default=PROMOTION_THRESHOLD)


def max_bloat_for_promotion() -> float:
    return float(os.environ.get("DOOFUS_MAX_BLOAT_PENALTY_FOR_PROMOTION", "0.20"))


def require_replay_for_promotion() -> bool:
    return os.environ.get("DOOFUS_REQUIRE_REPLAY_FOR_PROMOTION", "1") == "1"


def prequalify_candidate(scores: dict, baseline: float = 0.5) -> dict:
    promo_baseline = effective_promotion_baseline(baseline)
    score_total = float(scores.get("score_total") or 0)
    threshold = active_promotion_threshold()
    replay_ok = scores.get("score_replay", 0) >= 0.45
    reason = ""
    eligible = True
    if scores.get("score_safety", 0) < 0.99:
        eligible = False
        reason = "safety_violation"
    elif score_total < threshold or score_total <= promo_baseline:
        eligible = False
        reason = "below_threshold"
    elif scores.get("bloat_penalty", 0) > max_bloat_for_promotion():
        eligible = False
        reason = "bloat"
    elif require_replay_for_promotion() and not replay_ok:
        eligible = False
        reason = "replay_failed"
    return {
        "eligible_for_expensive_scoring": eligible,
        "prequal_reason": reason,
        "promotion_threshold": threshold,
        "promotion_baseline": promo_baseline,
        "replay_passed": replay_ok,
    }


def evaluate_promotion(
    candidate: dict,
    scores: dict,
    baseline: float = 0.5,
    *,
    arena_results: list[dict] | None = None,
    fake_proof: bool = False,
    precomputed_card: dict | None = None,
) -> dict:
    arena_results = arena_results or []
    if evidence_based_proof_density():
        card = precomputed_card or build_scorecard(candidate, scores, arena_results=arena_results)
        scores = card["scores"]
    proof = check_proof_density(candidate, scores)
    arena = check_arena_support(arena_results)
    replay_ok = scores.get("score_replay", 0) >= 0.45
    if require_replay_for_promotion() and not replay_ok:
        replay_ok = False

    promo_baseline = effective_promotion_baseline(baseline)
    score_total = float(scores.get("score_total") or 0)
    threshold = active_promotion_threshold()
    score_ok = (
        scores.get("score_safety", 0) >= 0.99
        and score_total >= threshold
        and score_total > promo_baseline
        and scores.get("bloat_penalty", 0) <= max_bloat_for_promotion()
        and replay_ok
        and not fake_proof
    )
    full_promote = score_ok and proof["proof_density_passed"] and arena["arena_support_passed"]
    tier3_result: dict | None = None
    tier3_debt = False
    if full_promote:
        from doofus.promotion.tier3_final_gate import requires_tier3, run_tier3_final_gate

        if requires_tier3(score_total):
            tier3_result = run_tier3_final_gate(
                candidate,
                scores,
                arena_results=arena_results,
                baseline=baseline,
                gate_checks={
                    "proof_density_passed": proof["proof_density_passed"],
                    "arena_support_passed": arena["arena_support_passed"],
                    "replay_passed": replay_ok,
                },
            )
            if not tier3_result.get("passed"):
                full_promote = False
                tier3_debt = True
    shadow = score_ok and not full_promote and (proof["proof_debt"] or arena["arena_debt"] or tier3_debt)

    if full_promote:
        status = "promoted"
        promoted = True
    elif shadow:
        status = "shadow_promoted"
        promoted = False
    else:
        status = "rejected"
        promoted = False

    return {
        "promoted": promoted,
        "shadow_promoted": shadow,
        "promotion_status": status,
        "baseline_retained": not promoted,
        "proof_density_passed": proof["proof_density_passed"],
        "arena_support_passed": arena["arena_support_passed"],
        "proof_debt": proof["proof_debt"],
        "arena_debt": arena["arena_debt"],
        "replay_passed": replay_ok,
        "promotion_threshold": threshold,
        "promotion_baseline": promo_baseline,
        "tier3_result": tier3_result,
        "tier3_debt": tier3_debt,
    }
