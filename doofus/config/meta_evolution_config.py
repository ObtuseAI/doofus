"""Meta-evolution runtime defaults (SOTA recursive platform)."""
from __future__ import annotations

import os

DEFAULTS: dict[str, str] = {
    "DOOFUS_META_EVOLUTION_MODE": "1",
    "DOOFUS_ARENA_MODE": "live",
    "DOOFUS_MAP_ELITES_MODE": "1",
    "DOOFUS_GEPA_MODE": "1",
    "DOOFUS_GEPA_BATCH_EVERY": "3",
    "DOOFUS_GEPA_MIN_TRACES": "5",
    "DOOFUS_CODEEVOLVE_MODE": "1",
    "DOOFUS_CODEEVOLVE_EVERY": "20",
    "DOOFUS_CODEEVOLVE_AUTO_APPLY": "1",
    "DOOFUS_EXTERNAL_TARGETS_MODE": "0",
    "DOOFUS_AEVOLVE_MODE": "1",
    "DOOFUS_META_METACOGNITION_EVERY": "20",
    "DOOFUS_CAPSULE_INJECTION_RATE": "0.35",
    "DOOFUS_MAP_ELITES_MAINTAIN_EVERY": "8",
    "DOOFUS_ARENA_LIVE_MAX_PER_CYCLE": "4",
    "DOOFUS_ARENA_TIMEOUT_SECONDS": "60",
    "DOOFUS_TIER3_ENABLED": "0",
    "DOOFUS_TIER3_MIN_SCORE": "0.85",
}


def apply_defaults(*, force: bool = False) -> dict[str, str]:
    applied: dict[str, str] = {}
    for key, value in DEFAULTS.items():
        if force or key not in os.environ:
            os.environ[key] = value
            applied[key] = value
    return applied


def meta_evolution_enabled() -> bool:
    return os.environ.get("DOOFUS_META_EVOLUTION_MODE", "1") == "1"


def arena_mode() -> str:
    return os.environ.get("DOOFUS_ARENA_MODE", "hybrid")


def map_elites_enabled() -> bool:
    return os.environ.get("DOOFUS_MAP_ELITES_MODE", "1") == "1"


def gepa_enabled() -> bool:
    return os.environ.get("DOOFUS_GEPA_MODE", "1") == "1"


def codeevolve_enabled() -> bool:
    return os.environ.get("DOOFUS_CODEEVOLVE_MODE", "1") == "1"


def aevolve_enabled() -> bool:
    return os.environ.get("DOOFUS_AEVOLVE_MODE", "1") == "1"


def codeevolve_auto_apply() -> bool:
    return os.environ.get("DOOFUS_CODEEVOLVE_AUTO_APPLY", DEFAULTS["DOOFUS_CODEEVOLVE_AUTO_APPLY"]) == "1"


def external_targets_enabled() -> bool:
    return os.environ.get("DOOFUS_EXTERNAL_TARGETS_MODE", DEFAULTS["DOOFUS_EXTERNAL_TARGETS_MODE"]) == "1"


def runtime_snapshot() -> dict:
    return {k: os.environ.get(k, DEFAULTS.get(k)) for k in DEFAULTS}
