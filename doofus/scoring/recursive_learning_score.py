"""Recursive learning heuristic."""
from __future__ import annotations

def recursive_learning_score(candidate: dict, generation: int) -> float:
    traits = set(candidate.get("traits", []))
    base = 0.2 + min(0.4, generation * 0.02)
    if "generalization_pressure" in traits:
        base += 0.15
    if "replay_stability" in traits:
        base += 0.1
    return min(1.0, base)
