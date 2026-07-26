"""Regression audit — promoted candidate vs parent/baseline."""
from __future__ import annotations


def audit_regression(candidate: dict, parent: dict | None, baseline_score: float) -> dict:
    cand_score = float(candidate.get("score_total") or 0)
    parent_score = float(parent.get("score_total") or baseline_score) if parent else baseline_score
    delta = round(cand_score - parent_score, 4)
    vs_baseline = round(cand_score - baseline_score, 4)
    passed = delta > 0 and vs_baseline > 0
    if not passed and cand_score >= 0.72:
        verdict = "promotion_weak"
    elif not passed:
        verdict = "promotion_overfit"
    else:
        verdict = "regression_ok"
    return {
        "candidate_score": cand_score,
        "parent_score": parent_score,
        "baseline_score": baseline_score,
        "delta_vs_parent": delta,
        "delta_vs_baseline": vs_baseline,
        "regression_passed": passed,
        "regression_verdict": verdict,
    }
