"""Proof density gate for promotion."""
from __future__ import annotations

import os

DEFAULT_MIN = 0.55


def min_proof_density_score() -> float:
    return float(os.environ.get("DOOFUS_MIN_PROOF_DENSITY_SCORE", str(DEFAULT_MIN)))


def check_proof_density(candidate: dict, scores: dict) -> dict:
    score = float(scores.get("proof_density_score") or 0)
    traits = candidate.get("traits") or []
    if isinstance(traits, str):
        has_trait = "proof_density" in traits
    else:
        has_trait = "proof_density" in traits
    passed = score >= min_proof_density_score() or has_trait
    return {
        "proof_density_score": score,
        "proof_density_passed": passed,
        "min_proof_density": min_proof_density_score(),
        "proof_debt": not passed,
    }
