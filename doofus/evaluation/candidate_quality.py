"""Candidate quality analysis across generations (read-only)."""
from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any

from doofus.core.doofus_paths import METRICS_DB
from doofus.scoring.promotion_gate import PROMOTION_THRESHOLD

PROMOTION_THRESHOLD_FLOAT = float(PROMOTION_THRESHOLD)


def analyze_generation(conn: sqlite3.Connection, generation: int) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT candidate_id, status, rejection_reason, score_total, promotion_status
        FROM candidates WHERE generation=?
        """,
        (generation,),
    ).fetchall()
    reasons = Counter(r[2] or "unknown" for r in rows)
    promoted = sum(1 for r in rows if r[1] in ("promoted", "champion"))
    shadow = sum(1 for r in rows if r[1] == "shadow_promoted")
    rejected = sum(1 for r in rows if r[1] == "rejected")
    queued = sum(1 for r in rows if r[2] and "queued_for_proof_builder" in str(r[2]))
    above_threshold = sum(1 for r in rows if (r[3] or 0) >= PROMOTION_THRESHOLD_FLOAT)
    scores = [float(r[3] or 0) for r in rows if r[3] is not None]
    return {
        "generation": generation,
        "candidate_count": len(rows),
        "promoted": promoted,
        "shadow_promoted": shadow,
        "rejected": rejected,
        "queued_for_proof_builder": queued,
        "above_score_threshold": above_threshold,
        "dominant_rejection_reason": reasons.most_common(1)[0][0] if reasons else None,
        "rejection_reason_histogram": dict(reasons),
        "max_score": max(scores) if scores else None,
        "mean_score": round(sum(scores) / len(scores), 4) if scores else None,
    }


def analyze_generations(
    *,
    start_generation: int,
    end_generation: int,
    db_path=None,
) -> dict[str, Any]:
    path = db_path or METRICS_DB
    conn = sqlite3.connect(path, timeout=30)
    by_gen = [analyze_generation(conn, g) for g in range(start_generation, end_generation + 1)]
    conn.close()
    all_reasons: Counter = Counter()
    for g in by_gen:
        all_reasons.update(g.get("rejection_reason_histogram") or {})
    return {
        "classification": "DOOFUS_CANDIDATE_QUALITY_REPORT",
        "start_generation": start_generation,
        "end_generation": end_generation,
        "generations": by_gen,
        "aggregate_dominant_rejection_reason": all_reasons.most_common(1)[0][0] if all_reasons else None,
        "aggregate_rejection_histogram": dict(all_reasons),
        "zero_promotion_pattern": all(g.get("promoted", 0) == 0 for g in by_gen),
    }
