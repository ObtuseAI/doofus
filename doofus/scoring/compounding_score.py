"""Local compounding heuristic — not an AGI claim."""
from __future__ import annotations

def compounding_score(candidate: dict, prior_best: float = 0.0) -> float:
    traits = set(candidate.get("traits", []))
    base = 0.3 + 0.1 * len(traits)
    if "compounding_bias" in traits:
        base += 0.15
    if "proof_density" in traits:
        base += 0.1
    return min(1.0, base + max(0.0, prior_best * 0.05))
