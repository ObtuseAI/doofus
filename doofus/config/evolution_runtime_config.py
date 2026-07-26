"""Always-on evolution runtime defaults."""
from __future__ import annotations

import os

DEFAULTS: dict[str, str] = {
    "DOOFUS_EVOLUTION_PRESSURE_MODE": "1",
    "DOOFUS_BASE_CANDIDATES_PER_CYCLE": "16",
    "DOOFUS_MAX_CANDIDATES_PER_CYCLE": "48",
    "DOOFUS_STAGNATION_CYCLES_BEFORE_PRESSURE": "1",
    "DOOFUS_STAGNATION_CYCLES_FOR_SLACK": "6",
    "DOOFUS_STAGNATION_PROMOTION_SLACK": "0.025",
    "DOOFUS_CYCLE_SLEEP_SECONDS": "12",
    "DOOFUS_MIN_CYCLE_SLEEP_SECONDS": "4",
    "DOOFUS_ELITE_ARCHIVE_SIZE": "50",
    "DOOFUS_CHALLENGER_TOURNAMENT_SIZE": "16",
    "DOOFUS_ELITE_PARENT_WEIGHT": "0.55",
    "DOOFUS_BEST_EVER_PARENT_WEIGHT": "0.25",
    "DOOFUS_SHADOW_ELITE_PARENT_WEIGHT": "0.10",
    "DOOFUS_NOVELTY_PARENT_WEIGHT": "0.10",
    "DOOFUS_BRANCH_RETIREMENT_AFTER_REJECTIONS": "20",
    "DOOFUS_LINEAGE_ACCELERATION_ON_IMPROVEMENT": "1",
}


def apply_defaults(*, force: bool = False) -> dict[str, str]:
    applied: dict[str, str] = {}
    for key, value in DEFAULTS.items():
        if force or key not in os.environ:
            os.environ[key] = value
            applied[key] = value
    return applied


def evolution_pressure_enabled() -> bool:
    return os.environ.get("DOOFUS_EVOLUTION_PRESSURE_MODE", "1") == "1"


def runtime_snapshot() -> dict:
    return {k: os.environ.get(k, DEFAULTS.get(k)) for k in DEFAULTS}
