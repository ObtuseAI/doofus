"""Escalate algorithm exploration during stagnation."""
from __future__ import annotations

from doofus.meta.aevolve.algorithm_registry import ALGORITHMS, update_weight


def escalate(stagnation_cycles: int) -> dict:
    threshold = int(__import__("os").environ.get("DOOFUS_AEVOLVE_ESCALATION_AT", "10"))
    if stagnation_cycles < threshold:
        return {"escalated": False, "stagnation_cycles": stagnation_cycles}
    underused = ["gene_crossover", "map_elites_niche", "gepa_reflective"]
    for algo in underused:
        update_weight(algo, ALGORITHMS[algo]["weight"] * 1.5)
    return {
        "escalated": True,
        "stagnation_cycles": stagnation_cycles,
        "boosted": underused,
    }
