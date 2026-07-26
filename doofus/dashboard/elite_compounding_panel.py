"""Elite compounding dashboard panel."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import STATE
from doofus.evolution.elite_archive import get_elite_archive
from doofus.evolution.best_ever_ledger import get_best_ever


def get_elite_compounding_panel() -> dict:
    elite = get_elite_archive()
    best = get_best_ever()
    comp_path = STATE / "autonomous_compounding_last.json"
    last = json.loads(comp_path.read_text(encoding="utf-8")) if comp_path.exists() else {}
    return {
        "elite_archive_count": elite.get("elite_archive_count", 0),
        "best_ever_score": best.get("best_ever_score") or best.get("best_score"),
        "best_ever_candidate_id": best.get("best_ever_candidate_id") or best.get("best_candidate_id"),
        "parent_pool_size": last.get("parent_pool_size", 0),
        "parent_sources": last.get("parent_sources", []),
    }
