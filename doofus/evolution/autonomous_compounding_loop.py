"""Autonomous compounding after each cycle."""
from __future__ import annotations

from doofus.evolution.elite_archive import get_elite_archive
from doofus.evolution.shadow_elite_archive import get_shadow_elite_archive
from doofus.evolution.best_ever_ledger import get_best_ever
from doofus.evolution.elite_parent_selector import select_parents


def after_compounding_cycle(*, promoted: int, generation: int) -> dict:
    elite = get_elite_archive()
    shadow = get_shadow_elite_archive()
    best = get_best_ever()
    parents = select_parents(limit=10)
    result = {
        "generation": generation,
        "promoted_this_cycle": promoted,
        "elite_archive_count": elite.get("elite_archive_count", 0),
        "shadow_elite_count": shadow.get("shadow_elite_count", 0),
        "best_ever_score": best.get("best_ever_score"),
        "best_ever_candidate_id": best.get("best_ever_candidate_id"),
        "parent_pool_size": len(parents),
        "parent_sources": [p.get("source", "elite") for p in parents[:5]],
    }
    from doofus.core.doofus_paths import STATE
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "autonomous_compounding_last.json").write_text(__import__("json").dumps(result, indent=2), encoding="utf-8")
    return result
