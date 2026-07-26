"""Elite archive growth dashboard panel."""
from __future__ import annotations

from doofus.evolution.elite_archive import get_elite_archive
from doofus.evolution.best_ever_ledger import get_best_ever


def get_elite_archive_growth_panel() -> dict:
    elite = get_elite_archive()
    best = get_best_ever()
    return {
        "count": elite.get("elite_archive_count", 0),
        "size_cap": elite.get("size_cap", 25),
        "usage": elite.get("usage", {}),
        "best_ever_score": best.get("best_ever_score"),
        "best_ever_candidate_id": best.get("best_ever_candidate_id"),
        "entries_preview": elite.get("entries", [])[:5],
    }
