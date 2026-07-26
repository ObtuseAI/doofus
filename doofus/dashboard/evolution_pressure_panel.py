"""Evolution pressure dashboard panel."""
from __future__ import annotations

from doofus.evolution.evolution_pressure_mode import get_evolution_snapshot


def get_evolution_pressure_panel() -> dict:
    snap = get_evolution_snapshot()
    return {
        "enabled": snap.get("enabled", False),
        "pressure_level": snap.get("pressure_level", 1.0),
        "stagnation_cycles": snap.get("stagnation_cycles", 0),
        "candidate_count_next": snap.get("candidate_count_next", 3),
        "elite_archive_count": snap.get("elite_archive_count", 0),
        "best_ever_score": snap.get("best_ever_score", 0),
        "best_ever_candidate_id": snap.get("best_ever_candidate_id"),
        "challenger_tournament_count": snap.get("challenger_tournament_count", 0),
        "retired_branch_count": snap.get("retired_branch_count", 0),
    }
