"""Meta evolution dashboard panel."""
from __future__ import annotations

from doofus.meta.recursive_supervisor import get_meta_snapshot
from doofus.evolution.map_elites_archive import get_snapshot as map_snapshot
from doofus.meta.gepa.prompt_store import snapshot as gepa_snapshot
from doofus.meta.gep.capsule_store import get_snapshot as gep_snapshot
from doofus.meta.aevolve.algorithm_selector import get_snapshot as aevolve_snapshot
from doofus.meta.codeevolve.rollback_manager import get_snapshot as codeevolve_snapshot
from doofus.config.meta_evolution_config import runtime_snapshot
from doofus.promotion.tier3_final_gate import get_tier3_snapshot


def get_meta_evolution_panel() -> dict:
    return {
        "classification": "META_EVOLUTION_PANEL",
        "config": runtime_snapshot(),
        "meta_state": get_meta_snapshot(),
        "map_elites": map_snapshot(),
        "gepa": gepa_snapshot(),
        "gep": gep_snapshot(),
        "aevolve": aevolve_snapshot(),
        "codeevolve": codeevolve_snapshot(),
        "tier3": get_tier3_snapshot(),
    }
