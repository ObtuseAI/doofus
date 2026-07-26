"""Novelty pressure — reduce local minima stagnation."""
from __future__ import annotations

import hashlib

from doofus.evolution.evolution_policy import novelty_pressure_weight


def novelty_score(candidate: dict) -> float:
    traits = candidate.get("traits") or []
    if isinstance(traits, str):
        trait_key = traits
    else:
        trait_key = ",".join(sorted(str(t) for t in traits))
    parent = candidate.get("parent_id") or ""
    digest = hashlib.sha256(f"{parent}:{trait_key}".encode()).hexdigest()
    base = int(digest[:8], 16) / 0xFFFFFFFF
    return round(base * novelty_pressure_weight(), 4)


def apply_novelty_bonus(scores: dict, candidate: dict) -> dict:
    bonus = novelty_score(candidate)
    total = min(1.0, float(scores.get("score_total", 0)) + bonus)
    out = dict(scores)
    out["novelty_score"] = bonus
    out["score_total"] = round(total, 4)
    return out
