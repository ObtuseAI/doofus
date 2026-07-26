"""Promotion audit — validate promoted candidates against gate criteria."""
from __future__ import annotations

import sqlite3
from typing import Any

from doofus.core.doofus_paths import METRICS_DB
from doofus.core.doofus_state import init_db
from doofus.scoring.promotion_bloat_audit import audit_bloat
from doofus.scoring.promotion_gate import PROMOTION_THRESHOLD, evaluate_promotion
from doofus.scoring.promotion_regression_audit import audit_regression
from doofus.scoring.promotion_replay_audit import audit_replay
from doofus.scoring.promotion_safety_audit import audit_safety


def _fetch_candidate(conn: sqlite3.Connection, candidate_id: str) -> dict | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
    return dict(row) if row else None


def _arena_support(conn: sqlite3.Connection, candidate_id: str) -> dict:
    rows = conn.execute(
        "SELECT arena, result FROM arena_results WHERE candidate_id = ?", (candidate_id,)
    ).fetchall()
    wins = sum(1 for _, r in rows if str(r).lower() in ("win", "pass", "ok"))
    return {"arena_count": len(rows), "arena_wins": wins, "arena_support": len(rows) > 0 and wins > 0}


def _lineage_support(candidate: dict) -> bool:
    return bool(candidate.get("parent_id"))


def _overall_verdict(parts: dict) -> str:
    if parts.get("safety_verdict") == "promotion_safety_blocked":
        return "promotion_safety_blocked"
    if parts.get("replay_verdict") == "promotion_unreplayable":
        return "promotion_unreplayable"
    if parts.get("bloat_verdict") == "promotion_bloated":
        return "promotion_bloated"
    if parts.get("regression_verdict") in ("promotion_weak", "promotion_overfit"):
        return parts["regression_verdict"]
    if not parts.get("proof_exists"):
        return "promotion_missing_proof"
    if parts.get("gate_would_promote") and parts.get("regression_passed"):
        notes = []
        if parts.get("delta_vs_baseline", 0) < 0.05:
            notes.append("small_delta")
        if not parts.get("arena_support"):
            notes.append("no_arena_support")
        if notes:
            return "promotion_validated_with_notes"
        return "promotion_validated"
    return "promotion_weak"


def audit_single_promotion(
    conn: sqlite3.Connection,
    promotion_row: dict,
    *,
    baseline_score: float = 0.5,
) -> dict:
    cid = promotion_row["candidate_id"]
    candidate = _fetch_candidate(conn, cid)
    if not candidate:
        return {
            "candidate_id": cid,
            "promotion_timestamp": promotion_row.get("created_at"),
            "verdict": "promotion_unreplayable",
            "error": "candidate_not_found",
        }

    parent = _fetch_candidate(conn, candidate.get("parent_id")) if candidate.get("parent_id") else None
    scores = {
        "score_total": candidate.get("score_total"),
        "score_safety": candidate.get("score_safety"),
        "score_replay": candidate.get("score_replay"),
        "bloat_penalty": candidate.get("bloat_penalty", 0),
    }
    gate = evaluate_promotion(candidate, scores, baseline_score)
    replay = audit_replay(candidate)
    regression = audit_regression(candidate, parent, baseline_score)
    bloat = audit_bloat(candidate)
    safety = audit_safety(candidate)
    arena = _arena_support(conn, cid)
    proof_exists = float(candidate.get("proof_density_score") or 0) >= 0.45 or "proof_density" in str(
        candidate.get("traits", "")
    )

    parts = {
        **replay,
        **regression,
        **bloat,
        **safety,
        **arena,
        "candidate_id": cid,
        "parent_id": candidate.get("parent_id"),
        "generation": candidate.get("generation"),
        "promotion_timestamp": promotion_row.get("created_at"),
        "promotion_reason": candidate.get("promotion_status", "promoted"),
        "proof_density_score": candidate.get("proof_density_score"),
        "proof_exists": proof_exists,
        "lineage_support": _lineage_support(candidate),
        "gate_would_promote": gate.get("promoted", False),
        "forced_promotion": False,
        "rejection_would_be_better": regression.get("delta_vs_baseline", 0) < 0.02,
        "generalization_score": candidate.get("score_generalization"),
        "compounding_score": candidate.get("score_compounding"),
        "recursive_learning_score": candidate.get("score_recursive_learning"),
        "promotion_threshold": PROMOTION_THRESHOLD,
    }
    parts["verdict"] = _overall_verdict(parts)
    if parts["verdict"] == "promotion_weak" and parts.get("rejection_would_be_better"):
        parts["rollback_recommended"] = parts["verdict"] in (
            "promotion_safety_blocked",
            "promotion_unreplayable",
        )
    else:
        parts["rollback_recommended"] = parts["verdict"] in (
            "promotion_safety_blocked",
            "promotion_unreplayable",
        )
    return parts


def audit_promotions(*, since: str | None = None, limit: int = 10) -> dict[str, Any]:
    init_db()
    conn = sqlite3.connect(METRICS_DB, timeout=5.0)
    conn.row_factory = sqlite3.Row
    if since:
        promos = conn.execute(
            "SELECT * FROM promotions WHERE created_at >= ? ORDER BY id DESC",
            (since,),
        ).fetchall()
    else:
        promos = conn.execute("SELECT * FROM promotions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    if not promos and since:
        promos = conn.execute("SELECT * FROM promotions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        scope = "historical_fallback"
    elif since and promos:
        scope = "burn_in_window"
    else:
        scope = "recent"

    baseline = 0.5
    try:
        cp = conn.execute(
            "SELECT score_total FROM candidates WHERE status='promoted' ORDER BY score_total DESC LIMIT 1"
        ).fetchone()
        if cp:
            baseline = float(cp[0]) * 0.9
    except Exception:
        pass

    results = [audit_single_promotion(conn, dict(p), baseline_score=baseline) for p in promos]
    conn.close()

    verdicts = [r.get("verdict") for r in results]
    summary = {
        "scope": scope,
        "since_filter": since,
        "promotions_audited": len(results),
        "validated": sum(1 for v in verdicts if v in ("promotion_validated", "promotion_validated_with_notes")),
        "weak": sum(1 for v in verdicts if v in ("promotion_weak", "promotion_overfit")),
        "unsafe": sum(1 for v in verdicts if v == "promotion_safety_blocked"),
        "unreplayable": sum(1 for v in verdicts if v == "promotion_unreplayable"),
        "bloated": sum(1 for v in verdicts if v == "promotion_bloated"),
        "missing_proof": sum(1 for v in verdicts if v == "promotion_missing_proof"),
        "rollback_recommended": sum(1 for r in results if r.get("rollback_recommended")),
    }
    return {"summary": summary, "promotions": results}
