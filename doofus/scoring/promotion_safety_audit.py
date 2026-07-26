"""Safety audit for promoted candidates."""
from __future__ import annotations

from doofus.safety.doofus_safety_gate import check_candidate_safety

MIN_SAFETY = 0.99


def audit_safety(candidate: dict) -> dict:
    safety = check_candidate_safety(candidate)
    score = float(candidate.get("score_safety") or safety.get("score_safety") or 0)
    passed = safety.get("passes", False) and score >= MIN_SAFETY
    return {
        "score_safety": score,
        "safety_passed": passed,
        "violations": safety.get("violations", []),
        "safety_verdict": "safety_ok" if passed else "promotion_safety_blocked",
        "min_safety_threshold": MIN_SAFETY,
    }
