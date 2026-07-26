"""Reconcile candidate table scores with component metrics for gates."""
from __future__ import annotations


def reconcile_scores(candidate: dict, scores: dict) -> dict:
    """Use authoritative candidate.score_total when higher than stale components."""
    out = dict(scores)
    table_total = candidate.get("score_total")
    if table_total is not None:
        out["score_total"] = max(float(out.get("score_total") or 0), float(table_total))
    return out
