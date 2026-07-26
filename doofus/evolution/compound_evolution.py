"""Compounding helpers — adaptive promotion bar during stagnation."""
from __future__ import annotations

import os

from doofus.evolution.adaptive_mutation_pressure import get_pressure_state
from doofus.evolution.best_ever_ledger import get_best_ever


def stagnation_promotion_slack() -> float:
    return float(os.environ.get("DOOFUS_STAGNATION_PROMOTION_SLACK", "0.015"))


def stagnation_cycles_for_slack() -> int:
    return int(os.environ.get("DOOFUS_STAGNATION_CYCLES_FOR_SLACK", "10"))


def effective_promotion_baseline(checkpoint_baseline: float) -> float:
    """During long stagnation, allow promotion within slack of best-ever (still safety-gated)."""
    best = float(get_best_ever().get("best_score") or checkpoint_baseline)
    stagnation = int(get_pressure_state().get("stagnation_cycles", 0))
    if stagnation >= stagnation_cycles_for_slack() and best > 0:
        floor = best * (1.0 - stagnation_promotion_slack())
        return min(float(checkpoint_baseline), floor)
    return float(checkpoint_baseline)
