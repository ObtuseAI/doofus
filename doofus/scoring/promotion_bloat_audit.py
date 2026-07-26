"""Bloat audit for promoted candidates."""
from __future__ import annotations

MAX_BLOAT = 0.3


def audit_bloat(candidate: dict) -> dict:
    traits = candidate.get("traits") or []
    if isinstance(traits, str):
        trait_count = len(traits.split(",")) if traits else 0
    else:
        trait_count = len(traits)
    bloat = float(candidate.get("bloat_penalty") or max(0, 0.1 * (trait_count - 5)))
    passed = bloat <= MAX_BLOAT
    return {
        "trait_count": trait_count,
        "bloat_penalty": bloat,
        "bloat_passed": passed,
        "bloat_verdict": "bloat_ok" if passed else "promotion_bloated",
        "max_bloat_threshold": MAX_BLOAT,
    }
