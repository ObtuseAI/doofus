"""MAP-Elites weighted parent selection."""
from __future__ import annotations

import random

from doofus.config.meta_evolution_config import map_elites_enabled
from doofus.evolution.map_elites_archive import load_all
from doofus.evolution.elite_parent_selector import select_parents as flat_select_parents
from doofus.mutation.lineage_store import load_top_scoring_parents
from doofus.evolution.branch_retirement import is_branch_retired


def select_map_elites_parents(limit: int = 10, *, seed: int | None = None) -> list[dict]:
    """40% MAP cells, 40% flat elite, 20% novelty."""
    if not map_elites_enabled():
        return flat_select_parents(limit)

    rng = random.Random(seed)
    cells = load_all()
    map_pool = [c for c in cells if c.get("candidate_id") and not is_branch_retired(c.get("candidate_id"))]
    map_pool.sort(key=lambda e: float(e.get("fitness") or 0), reverse=True)
    if len(map_pool) > limit:
        map_pool = rng.sample(map_pool[: limit * 3], k=min(len(map_pool), limit * 2))
        map_pool.sort(key=lambda e: float(e.get("fitness") or 0), reverse=True)

    flat_pool = flat_select_parents(limit=limit * 2)
    novelty = [
        p for p in load_top_scoring_parents(limit=limit)
        if not is_branch_retired(p.get("candidate_id"))
    ]

    n_map = max(1, int(limit * 0.4))
    n_flat = max(1, int(limit * 0.4))

    out: list[dict] = []
    seen: set[str] = set()

    for c in map_pool[:n_map]:
        cid = c.get("candidate_id")
        if cid and cid not in seen:
            seen.add(cid)
            out.append({
                "candidate_id": cid,
                "score_total": c.get("fitness"),
                "traits": c.get("traits"),
                "mutation_type": c.get("mutation_type"),
                "source": "map_elites",
                "cell_key": c.get("cell_key"),
            })

    for p in flat_pool:
        if len(out) >= n_map + n_flat:
            break
        cid = p.get("candidate_id")
        if cid and cid not in seen:
            seen.add(cid)
            out.append(dict(p))

    for p in novelty:
        if len(out) >= limit:
            break
        cid = p.get("candidate_id")
        if cid and cid not in seen:
            seen.add(cid)
            p = dict(p)
            p["source"] = "novelty"
            out.append(p)

    if len(out) < limit:
        for p in flat_pool:
            if len(out) >= limit:
                break
            cid = p.get("candidate_id")
            if cid and cid not in seen:
                seen.add(cid)
                out.append(dict(p))
    return out[:limit] if out else flat_select_parents(limit)
