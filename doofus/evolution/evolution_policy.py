"""Evolution policy constants and env."""
from __future__ import annotations

import os


def evolution_pressure_enabled() -> bool:
    return os.environ.get("DOOFUS_EVOLUTION_PRESSURE_MODE", "1") == "1"


def base_candidates_per_cycle() -> int:
    return int(os.environ.get("DOOFUS_BASE_CANDIDATES_PER_CYCLE", "16"))


def max_candidates_per_cycle() -> int:
    return int(os.environ.get("DOOFUS_MAX_CANDIDATES_PER_CYCLE", "48"))


def stagnation_cycles_before_pressure() -> int:
    return int(os.environ.get("DOOFUS_STAGNATION_CYCLES_BEFORE_PRESSURE", "1"))


def elite_archive_size() -> int:
    return int(os.environ.get("DOOFUS_ELITE_ARCHIVE_SIZE", "25"))


def challenger_tournament_size() -> int:
    return int(os.environ.get("DOOFUS_CHALLENGER_TOURNAMENT_SIZE", "8"))


def branch_retirement_after_rejections() -> int:
    return int(os.environ.get("DOOFUS_BRANCH_RETIREMENT_AFTER_REJECTIONS", "20"))


def novelty_pressure_weight() -> float:
    return float(os.environ.get("DOOFUS_NOVELTY_PRESSURE_WEIGHT", "0.15"))
