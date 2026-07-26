"""Promotion gate recommendation from audit evidence."""
from __future__ import annotations

from doofus.scoring.promotion_gate import PROMOTION_THRESHOLD


def recommend_gate(audit_result: dict) -> dict:
    s = audit_result.get("summary", {})
    promos = audit_result.get("promotions", [])
    n = max(s.get("promotions_audited", 0), 1)

    weak_rate = s.get("weak", 0) / n
    unsafe_rate = s.get("unsafe", 0) / n
    unreplay_rate = s.get("unreplayable", 0) / n
    validated_rate = s.get("validated", 0) / n

    deltas = [float(p.get("delta_vs_baseline", 0)) for p in promos if p.get("delta_vs_baseline") is not None]
    avg_delta = sum(deltas) / len(deltas) if deltas else 0.0
    sorted_d = sorted(deltas)
    median_delta = sorted_d[len(sorted_d) // 2] if sorted_d else 0.0

    replay_pass = sum(1 for p in promos if p.get("replay_passed")) / n
    regression_pass = sum(1 for p in promos if p.get("regression_passed")) / n
    bloat_pass = sum(1 for p in promos if p.get("bloat_passed")) / n
    safety_pass = sum(1 for p in promos if p.get("safety_passed")) / n

    recommendation = "keep_gate_current"
    why = "Promotion gate behavior appears acceptable for current sample."
    risk = "low"
    rollback_plan = "No gate change; continue monitoring."

    if unsafe_rate > 0:
        recommendation = "temporary_promotion_freeze"
        why = f"{s.get('unsafe', 0)} unsafe promotion(s) detected."
        risk = "high"
        rollback_plan = "Freeze promotions until safety audit passes on all candidates."
    elif unreplay_rate > 0.2:
        recommendation = "require_extra_replay"
        why = f"Unreplayable promotion rate {unreplay_rate:.0%} exceeds 20%."
        risk = "medium"
        rollback_plan = "Raise replay minimum or require second replay pass before promotion."
    elif weak_rate > 0.4:
        recommendation = "raise_promotion_threshold"
        why = f"Weak promotion rate {weak_rate:.0%}; avg delta {avg_delta:.3f}."
        risk = "medium"
        rollback_plan = "Revert threshold if promotion count drops to zero for 24h."
    elif avg_delta < 0.03 and validated_rate > 0:
        recommendation = "require_higher_proof_density"
        why = f"Promotions validate but median delta {median_delta:.3f} is marginal."
        risk = "medium"
        rollback_plan = "Monitor proof_density trait requirement for one burn-in cycle."
    elif s.get("rollback_recommended", 0) > 0:
        recommendation = "rollback_specific_promotion"
        why = f"{s.get('rollback_recommended')} promotion(s) flagged for rollback review."
        risk = "medium"
        rollback_plan = "Manual review of flagged candidate_ids; no auto-rollback."

    recommended_threshold = PROMOTION_THRESHOLD
    if recommendation == "raise_promotion_threshold":
        recommended_threshold = round(min(0.85, PROMOTION_THRESHOLD + 0.05), 2)

    return {
        "recommendation": recommendation,
        "current_threshold": PROMOTION_THRESHOLD,
        "recommended_threshold": recommended_threshold,
        "why": why,
        "evidence": {
            "weak_rate": round(weak_rate, 4),
            "unsafe_rate": round(unsafe_rate, 4),
            "unreplayable_rate": round(unreplay_rate, 4),
            "validated_rate": round(validated_rate, 4),
            "avg_improvement_delta": round(avg_delta, 4),
            "median_improvement_delta": round(median_delta, 4),
            "replay_pass_rate": round(replay_pass, 4),
            "regression_pass_rate": round(regression_pass, 4),
            "bloat_pass_rate": round(bloat_pass, 4),
            "safety_pass_rate": round(safety_pass, 4),
        },
        "risk": risk,
        "rollback_plan": rollback_plan,
        "apply_change": False,
    }
