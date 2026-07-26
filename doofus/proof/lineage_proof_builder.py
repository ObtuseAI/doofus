"""Lineage proof builder."""
from __future__ import annotations

from doofus.core.metrics_db import connect_metrics_db


def build_lineage_proof(candidate: dict, scores: dict) -> dict:
    parent_id = candidate.get("parent_id")
    if not parent_id:
        return {"lineage_support": False, "lineage_delta": 0.0}
    conn = connect_metrics_db()
    row = conn.execute("SELECT score_total FROM candidates WHERE candidate_id=?", (parent_id,)).fetchone()
    conn.close()
    parent_score = float(row[0]) if row else 0.0
    delta = float(scores.get("score_total") or 0) - parent_score
    return {"lineage_support": delta > 0, "lineage_delta": round(delta, 4), "parent_score": parent_score}
