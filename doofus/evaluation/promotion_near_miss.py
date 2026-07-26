"""Promotion near-miss analysis (read-only)."""
from __future__ import annotations

from typing import Any

from doofus.evaluation.candidate_quality import analyze_generation
from doofus.core.doofus_paths import METRICS_DB
from doofus.proof.high_score_rejection_miner import mine_high_score_rejections
from doofus.scoring.promotion_gate import PROMOTION_THRESHOLD
import sqlite3


def find_near_misses(generation: int, *, db_path=None) -> dict[str, Any]:
    path = db_path or METRICS_DB
    conn = sqlite3.connect(path, timeout=30)
    gen_summary = analyze_generation(conn, generation)
    conn.close()

    miner = mine_high_score_rejections(min_score=float(PROMOTION_THRESHOLD), limit=25, enrich=True)
    closest = miner.get("closest_to_promotion_top_25") or []
    proof_blocked = miner.get("proof_density_blocked_top_50") or []

    near_misses = []
    for row in closest[:25]:
        cid = row.get("candidate_id")
        score = row.get("score_total")
        reason = row.get("rejection_reason")
        if score is None:
            continue
        if float(score) >= float(PROMOTION_THRESHOLD):
            near_misses.append(
                {
                    "candidate_id": cid,
                    "score_total": score,
                    "rejection_reason": reason,
                    "generation": row.get("generation"),
                }
            )

    best = near_misses[0] if near_misses else (closest[0] if closest else None)
    return {
        "classification": "DOOFUS_PROMOTION_NEAR_MISS_REPORT",
        "generation": generation,
        "near_miss_count": len(near_misses),
        "near_misses": near_misses[:10],
        "best_near_miss_candidate": best.get("candidate_id") if best else None,
        "best_near_miss_score": best.get("score_total") if best else None,
        "proof_density_blocked_count": len(proof_blocked),
        "gen_summary": gen_summary,
        "miner_decision": miner.get("decision"),
    }


def analyze_generations_near_miss(start: int, end: int) -> dict[str, Any]:
    reports = [find_near_misses(g) for g in range(start, end + 1)]
    best_overall = None
    for r in reports:
        if r.get("best_near_miss_candidate"):
            if best_overall is None or (r.get("best_near_miss_score") or 0) > (best_overall.get("best_near_miss_score") or 0):
                best_overall = r
    return {
        "classification": "DOOFUS_PROMOTION_NEAR_MISS_MULTI_GEN",
        "start_generation": start,
        "end_generation": end,
        "reports": reports,
        "best_near_miss_generation": best_overall.get("generation") if best_overall else None,
        "best_near_miss_candidate": best_overall.get("best_near_miss_candidate") if best_overall else None,
        "total_near_miss_count": sum(r.get("near_miss_count", 0) for r in reports),
    }
