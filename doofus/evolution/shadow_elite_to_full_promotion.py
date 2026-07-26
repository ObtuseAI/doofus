"""Upgrade shadow elite to full promotion when proof gate passes."""
from __future__ import annotations

import json
import sqlite3

from doofus.core.doofus_paths import METRICS_DB, STATE
from doofus.core.doofus_events import utc_now
from doofus.evolution.shadow_elite_archive import mark_upgraded
from doofus.evolution.elite_archive import add_elite
from doofus.evolution.compound_evolution import effective_promotion_baseline
from doofus.scoring.promotion_gate import evaluate_promotion

AUDIT = STATE / "shadow_elite_upgrade_audit.json"


def _record_audit(entry: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    rows = json.loads(AUDIT.read_text(encoding="utf-8")) if AUDIT.exists() else []
    rows.append(entry)
    AUDIT.write_text(json.dumps(rows[-200:], indent=2), encoding="utf-8")


def try_upgrade_to_full(
    candidate: dict,
    scores: dict,
    arena_results: list[dict],
    *,
    baseline: float = 0.5,
    conn: sqlite3.Connection | None = None,
) -> dict:
    promo_baseline = effective_promotion_baseline(baseline)
    promo = evaluate_promotion(candidate, scores, baseline=promo_baseline, arena_results=arena_results)
    gates_ok = (
        promo.get("proof_density_passed")
        and promo.get("arena_support_passed")
        and promo.get("replay_passed")
        and float(scores.get("score_safety") or 0) >= 0.99
        and float(scores.get("score_total") or 0) >= 0.72
        and float(scores.get("score_total") or 0) > promo_baseline
        and float(scores.get("bloat_penalty") or 0) <= 0.20
        and not promo.get("forced_promotion")
    )
    if not promo.get("promoted") and not gates_ok:
        return {"upgraded": False, "promo": promo, "reason": promo.get("rejection_reason", "gates_failed")}
    own = conn is None
    if own:
        conn = sqlite3.connect(METRICS_DB, timeout=10.0)
    existing = conn.execute(
        "SELECT 1 FROM promotions WHERE candidate_id=?", (candidate["candidate_id"],)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO promotions (candidate_id, created_at) VALUES (?,?)",
            (candidate["candidate_id"], utc_now()),
        )
    conn.execute(
        "UPDATE candidates SET status='promoted', promotion_status='promoted' WHERE candidate_id=?",
        (candidate["candidate_id"],),
    )
    if own:
        conn.commit()
        conn.close()
    mark_upgraded(candidate["candidate_id"])
    add_elite({**candidate, "source": "shadow_upgrade"}, float(scores.get("score_total") or 0))
    _record_audit({
        "candidate_id": candidate["candidate_id"],
        "score": scores.get("score_total"),
        "proof_density": scores.get("proof_density_score"),
        "at": utc_now(),
        "evidence": {"arena_count": len(arena_results), "promo": {k: promo.get(k) for k in ("proof_density_passed", "arena_support_passed", "replay_passed")}},
    })
    return {"upgraded": True, "promo": promo}
