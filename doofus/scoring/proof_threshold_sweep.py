"""Offline proof-density threshold sweep on mined candidates."""
from __future__ import annotations

import sqlite3

from doofus.core.doofus_paths import METRICS_DB
from doofus.core.doofus_state import init_db
from doofus.proof.high_score_rejection_miner import mine_high_score_rejections
from doofus.proof.proof_density_calculator import calculate_proof_density
from doofus.scoring.promotion_gate import PROMOTION_THRESHOLD

THRESHOLDS = [0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65]


def sweep(*, min_score: float = PROMOTION_THRESHOLD) -> dict:
    init_db()
    mined = mine_high_score_rejections(min_score=min_score)
    candidates = mined.get("closest_to_promotion_top_25") or mined.get("top_100", [])[:50]
    conn = sqlite3.connect(METRICS_DB, timeout=10.0)
    enriched = []
    for c in candidates:
        cid = c["candidate_id"]
        scores = {r[0]: r[1] for r in conn.execute("SELECT metric, value FROM scores WHERE candidate_id=?", (cid,))}
        arena = [{"result": r[0]} for r in conn.execute("SELECT result FROM arena_results WHERE candidate_id=?", (cid,))]
        cand = {"candidate_id": cid, "parent_id": c.get("parent_id"), "traits": c.get("traits")}
        density = calculate_proof_density(cand, scores, arena_results=arena)
        enriched.append({**c, "computed_proof_density": density["proof_density_score"], "components": density["proof_components"]})
    conn.close()

    results = {}
    for t in THRESHOLDS:
        full = shadow = blocked = 0
        for e in enriched:
            pd = float(e.get("computed_proof_density") or e.get("proof_density_score") or 0)
            safety = float(e.get("score_safety") or 1.0) >= 0.99
            bloat = float(e.get("bloat_penalty") or 0) <= 0.20
            replay = float(e.get("score_replay") or 0) >= 0.45
            arena_ok = (e.get("arena_rows") or 0) > 0
            if not safety or not bloat or not replay:
                blocked += 1
            elif pd >= t and arena_ok:
                full += 1
            elif pd >= t * 0.8:
                shadow += 1
            else:
                blocked += 1
        results[str(t)] = {"full_promotion_candidates": full, "shadow_candidates": shadow, "blocked": blocked}

    current = 0.55
    cur_full = results[str(current)]["full_promotion_candidates"]
    best_t = current
    best_full = cur_full
    for t in [0.45, 0.50, 0.55, 0.60]:
        ts = str(t)
        if ts in results and results[ts]["full_promotion_candidates"] > best_full:
            best_t = t
            best_full = results[ts]["full_promotion_candidates"]

    recommendation = "keep_threshold_fix_generator"
    adjust_to = None
    if best_t < current and best_full > cur_full + 2:
        recommendation = "lower_proof_density_min"
        adjust_to = max(0.45, best_t)
    elif cur_full == 0 and all(results[str(t)]["full_promotion_candidates"] == 0 for t in THRESHOLDS):
        recommendation = "fix_proof_generation_not_threshold"

    return {
        "thresholds": results,
        "current_threshold": current,
        "recommended_threshold": adjust_to,
        "recommendation": recommendation,
        "candidates_evaluated": len(enriched),
        "enriched_sample": enriched[:5],
    }
