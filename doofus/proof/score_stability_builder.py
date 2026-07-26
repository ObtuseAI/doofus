"""Score stability proof builder."""
from __future__ import annotations


def build_score_stability(candidate: dict, scores: dict) -> dict:
    stab = float(scores.get("replay_stability_score") or scores.get("score_replay") or 0)
    traits = candidate.get("traits") or []
    if isinstance(traits, str):
        has = "replay_stability" in traits
    else:
        has = "replay_stability" in traits
    stable = stab >= 0.55 or has
    return {"score_stability": stab, "stable": stable}
