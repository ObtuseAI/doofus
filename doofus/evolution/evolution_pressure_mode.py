"""Evolution pressure mode — orchestrates aggressive autonomous evolution."""
from __future__ import annotations

import sqlite3

from doofus.evolution.adaptive_mutation_pressure import get_pressure_state, record_cycle
from doofus.evolution.best_ever_ledger import get_best_ever, update_best_ever
from doofus.evolution.branch_retirement import get_retired_summary, is_branch_retired, record_rejection
from doofus.evolution.challenger_tournament import get_tournament_summary, run_tournament
from doofus.evolution.elite_archive import add_elite, get_elite_archive
from doofus.evolution.evolution_policy import evolution_pressure_enabled
from doofus.evolution.novelty_pressure import apply_novelty_bonus
from doofus.metacognition.runtime_control import active_candidate_count


def prepare_cycle() -> dict:
    if not evolution_pressure_enabled():
        result = {"enabled": False, "candidate_count": 3, "candidate_count_next": 3}
    else:
        ps = get_pressure_state()
        count = ps.get("candidate_count_next", 3)
        result = {"enabled": True, "candidate_count": count, "candidate_count_next": count, **ps}
    metacognitive_count = active_candidate_count()
    if metacognitive_count is None:
        return result
    return {
        **result,
        "candidate_count": metacognitive_count,
        "candidate_count_next": metacognitive_count,
        "metacognitive_candidate_override": True,
    }


def apply_pre_promotion_scores(candidate: dict, scores: dict) -> dict:
    """Novelty and other pre-gate score adjustments — run before evaluate_promotion."""
    if not evolution_pressure_enabled():
        return scores
    return apply_novelty_bonus(dict(scores), candidate)


def after_candidate_scored(
    candidate: dict,
    scores: dict,
    *,
    promoted: bool,
    shadow: bool = False,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Post-promotion side effects only (scores already include pre-promotion adjustments)."""
    if not evolution_pressure_enabled():
        return scores
    score_total = float(scores.get("score_total") or 0)
    if promoted or shadow or score_total >= float(get_best_ever().get("best_score") or 0):
        update_best_ever(candidate["candidate_id"], score_total, int(candidate.get("generation", 0)))
    if promoted:
        add_elite(candidate, score_total, conn=conn)
    if candidate.get("status") == "rejected" and not shadow:
        record_rejection(candidate.get("parent_id"))
    return scores


def after_cycle(*, generation: int, promoted: int, scored: list[dict], partial: bool = False) -> dict:
    if not evolution_pressure_enabled():
        return {"enabled": False}
    if not partial:
        record_cycle(generation=generation, promoted=promoted)
        if scored:
            run_tournament(scored)
    return get_evolution_snapshot()


def get_evolution_snapshot() -> dict:
    ps = get_pressure_state()
    best = get_best_ever()
    elite = get_elite_archive()
    tour = get_tournament_summary()
    retired = get_retired_summary()
    return {
        "enabled": evolution_pressure_enabled(),
        "pressure_level": ps.get("pressure_level", 1.0),
        "stagnation_cycles": ps.get("stagnation_cycles", 0),
        "candidate_count_next": ps.get("candidate_count_next", 3),
        "elite_archive_count": elite.get("elite_archive_count", 0),
        "best_ever_score": best.get("best_score", 0),
        "best_ever_candidate_id": best.get("best_candidate_id"),
        "challenger_tournament_count": tour.get("challenger_tournament_count", 0),
        "retired_branch_count": retired.get("retired_branch_count", 0),
    }


def filter_retired_parents(candidates: list[dict]) -> list[dict]:
    return [c for c in candidates if not is_branch_retired(c.get("parent_id"))]
