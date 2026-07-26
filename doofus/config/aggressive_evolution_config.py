# -*- coding: utf-8 -*-
"""High-throughput evolution profile - more variants, faster compounding."""
from __future__ import annotations

import os

DEFAULTS: dict[str, str] = {
    "DOOFUS_AGGRESSIVE_EVOLUTION_MODE": "1",
    # Throughput
    "DOOFUS_BASE_CANDIDATES_PER_CYCLE": "16",
    "DOOFUS_MAX_CANDIDATES_PER_CYCLE": "48",
    "DOOFUS_STAGNATION_CYCLES_BEFORE_PRESSURE": "1",
    "DOOFUS_MAX_PRESSURE_LEVEL": "6.0",
    "DOOFUS_PRESSURE_RAMP_STEP": "0.35",
    "DOOFUS_CYCLE_SLEEP_SECONDS": "12",
    "DOOFUS_MIN_CYCLE_SLEEP_SECONDS": "4",
    "DOOFUS_SUPERVISOR_STAGNATION_FAST_SLEEP_AT": "2",
    # Compounding / lineage
    "DOOFUS_ELITE_ARCHIVE_SIZE": "50",
    "DOOFUS_CHALLENGER_TOURNAMENT_SIZE": "16",
    "DOOFUS_ELITE_PARENT_WEIGHT": "0.45",
    "DOOFUS_BEST_EVER_PARENT_WEIGHT": "0.30",
    "DOOFUS_SHADOW_ELITE_PARENT_WEIGHT": "0.15",
    "DOOFUS_NOVELTY_PARENT_WEIGHT": "0.10",
    "DOOFUS_NOVELTY_PRESSURE_WEIGHT": "0.22",
    "DOOFUS_STAGNATION_CYCLES_FOR_SLACK": "6",
    "DOOFUS_STAGNATION_PROMOTION_SLACK": "0.025",
    "DOOFUS_BRANCH_RETIREMENT_AFTER_REJECTIONS": "30",
    "DOOFUS_TRAITS_MIN_PER_CANDIDATE": "3",
    "DOOFUS_TRAITS_MAX_PER_CANDIDATE": "6",
    "DOOFUS_CAPSULE_DOUBLE_INJECTION_RATE": "0.12",
    # Meta-evolution cadence
    "DOOFUS_GEPA_BATCH_EVERY": "3",
    "DOOFUS_GEPA_MIN_TRACES": "5",
    "DOOFUS_MAP_ELITES_MAINTAIN_EVERY": "8",
    "DOOFUS_CODEEVOLVE_EVERY": "20",
    "DOOFUS_CAPSULE_INJECTION_RATE": "0.35",
    "DOOFUS_AEVOLVE_ESCALATION_AT": "5",
    "DOOFUS_ARENA_LIVE_MAX_PER_CYCLE": "4",
    # Rescue / proof compounding
    "DOOFUS_INLINE_RESCUE_MAX_PER_CYCLE": "20",
    "DOOFUS_PROOF_BUILDER_TOP_N": "150",
    "DOOFUS_SHADOW_ELITE_ARCHIVE_SIZE": "80",
    # Budget headroom for live mutation volume (still capped)
    "DOOFUS_MAX_MODEL_CALLS_PER_HOUR": "120",
    "DOOFUS_MAX_DAILY_COST_USD": "15",
    "DOOFUS_MODEL_TEMPERATURE": "0.75",
}


def apply_defaults(*, force: bool = False) -> dict[str, str]:
    applied: dict[str, str] = {}
    for key, value in DEFAULTS.items():
        if force or key not in os.environ:
            os.environ[key] = value
            applied[key] = value
    return applied


def aggressive_evolution_enabled() -> bool:
    return os.environ.get("DOOFUS_AGGRESSIVE_EVOLUTION_MODE", "0") == "1"


def runtime_snapshot() -> dict:
    return {k: os.environ.get(k, DEFAULTS.get(k)) for k in DEFAULTS}
