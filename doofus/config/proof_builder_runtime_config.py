"""Always-on proof-builder / rescue runtime defaults."""
from __future__ import annotations

import os

DEFAULTS: dict[str, str] = {
    "DOOFUS_PROOF_BUILDER_MODE": "1",
    "DOOFUS_SHADOW_ELITE_MODE": "1",
    "DOOFUS_HIGH_SCORE_RESCUE_MODE": "1",
    "DOOFUS_EVIDENCE_BASED_PROOF_DENSITY": "1",
    "DOOFUS_PROOF_BUILDER_MAX_RETRIES": "3",
    "DOOFUS_PROOF_BUILDER_TOP_N": "100",
    "DOOFUS_SHADOW_ELITE_ARCHIVE_SIZE": "50",
    "DOOFUS_INLINE_RESCUE_MAX_PER_CYCLE": "10",
    "DOOFUS_INLINE_RESCUE_MAX_SECONDS": "180",
}


def apply_defaults(*, force: bool = False) -> dict[str, str]:
    applied: dict[str, str] = {}
    for key, value in DEFAULTS.items():
        if force or key not in os.environ:
            os.environ[key] = value
            applied[key] = value
    return applied


def proof_builder_mode() -> bool:
    return os.environ.get("DOOFUS_PROOF_BUILDER_MODE", "1") == "1"


def shadow_elite_mode() -> bool:
    return os.environ.get("DOOFUS_SHADOW_ELITE_MODE", "1") == "1"


def high_score_rescue_mode() -> bool:
    return os.environ.get("DOOFUS_HIGH_SCORE_RESCUE_MODE", "1") == "1"


def evidence_based_proof_density() -> bool:
    return os.environ.get("DOOFUS_EVIDENCE_BASED_PROOF_DENSITY", "1") == "1"


def inline_rescue_max_per_cycle() -> int:
    return int(os.environ.get("DOOFUS_INLINE_RESCUE_MAX_PER_CYCLE", "10"))


def inline_rescue_max_seconds() -> int:
    return int(os.environ.get("DOOFUS_INLINE_RESCUE_MAX_SECONDS", "180"))


def runtime_snapshot() -> dict:
    return {
        **{k: os.environ.get(k, DEFAULTS.get(k)) for k in DEFAULTS},
        "proof_builder_mode": proof_builder_mode(),
        "shadow_elite_mode": shadow_elite_mode(),
        "high_score_rescue_mode": high_score_rescue_mode(),
        "evidence_based_proof_density": evidence_based_proof_density(),
    }


def bootstrap_autonomous_runtime(*, force: bool = False) -> dict:
    from doofus.config.evolution_runtime_config import apply_defaults as apply_evo
    from doofus.config.meta_evolution_config import apply_defaults as apply_meta
    from doofus.config.aggressive_evolution_config import (
        aggressive_evolution_enabled,
        apply_defaults as apply_aggressive,
    )
    out = {
        "evolution": apply_evo(force=force),
        "proof_builder": apply_defaults(force=force),
        "meta_evolution": apply_meta(force=force),
    }
    if aggressive_evolution_enabled() or os.environ.get("DOOFUS_AGGRESSIVE_EVOLUTION_MODE") == "1":
        out["aggressive_evolution"] = apply_aggressive(force=force)
    return out
