"""Weighted elite / best-ever / shadow parent selection."""
from __future__ import annotations

import os
import random

from doofus.mutation.lineage_store import load_promoted_parents, load_top_scoring_parents
from doofus.evolution.shadow_elite_parent_selector import load_shadow_elite_parents
from doofus.evolution.best_ever_ledger import get_best_ever
from doofus.evolution.branch_retirement import is_branch_retired
from doofus.evolution.elite_archive import load_elite_parents, record_parent_usage


def _weight(name: str, default: str) -> float:
    return float(os.environ.get(name, default))


def select_parents(limit: int = 10) -> list[dict]:
    elite_w = _weight("DOOFUS_ELITE_PARENT_WEIGHT", "0.55")
    best_w = _weight("DOOFUS_BEST_EVER_PARENT_WEIGHT", "0.25")
    shadow_w = _weight("DOOFUS_SHADOW_ELITE_PARENT_WEIGHT", "0.10")
    novelty_w = _weight("DOOFUS_NOVELTY_PARENT_WEIGHT", "0.10")

    archive_elite = [p for p in load_elite_parents(limit=limit * 2) if not is_branch_retired(p.get("candidate_id"))]
    promoted = [p for p in load_promoted_parents(limit=limit * 2) if not is_branch_retired(p.get("candidate_id"))]
    seen_archive = {p.get("candidate_id") for p in archive_elite}
    elite_pool = archive_elite + [p for p in promoted if p.get("candidate_id") not in seen_archive]
    top = [p for p in load_top_scoring_parents(limit=limit) if not is_branch_retired(p.get("candidate_id"))]
    shadow = load_shadow_elite_parents(limit=limit)
    best = get_best_ever()
    best_parent = None
    if best.get("best_ever_candidate_id") or best.get("best_candidate_id"):
        best_parent = {
            "candidate_id": best.get("best_ever_candidate_id") or best.get("best_candidate_id"),
            "score_total": best.get("best_ever_score") or best.get("best_score"),
            "source": "best_ever",
        }

    pools: list[tuple[float, list, str]] = [
        (elite_w, elite_pool or top, "elite"),
        (best_w, [best_parent] if best_parent else [], "best_ever"),
        (shadow_w, shadow, "shadow"),
        (novelty_w, [], "novelty"),
    ]
    out: list[dict] = []
    seen: set[str] = set()
    sources: list[str] = []
    for weight, pool, label in pools:
        if not pool or weight <= 0:
            continue
        n = max(1, int(limit * weight))
        for p in pool[:n]:
            cid = p.get("candidate_id")
            if cid and cid not in seen:
                seen.add(cid)
                p = dict(p)
                p.setdefault("source", label)
                out.append(p)
                sources.append(label)
    record_parent_usage(sources)
    return out[:limit] if out else top[:limit]
