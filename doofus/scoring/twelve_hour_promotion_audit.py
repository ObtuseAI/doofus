"""12-hour promotion and shadow promotion audit."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from doofus.core.doofus_paths import METRICS_DB, TWELVE_HOUR_RUN_DIR
from doofus.core.doofus_state import init_db
from doofus.scoring.promotion_audit import audit_single_promotion

RUN_JSON = TWELVE_HOUR_RUN_DIR / "b1091_12_hour_unattended_run.json"


def audit_run(*, since: str | None = None) -> dict:
    init_db()
    conn = sqlite3.connect(METRICS_DB, timeout=5.0)
    conn.row_factory = sqlite3.Row

    if since:
        promos = conn.execute("SELECT * FROM promotions WHERE created_at >= ? ORDER BY id DESC", (since,)).fetchall()
        shadows = conn.execute(
            "SELECT * FROM candidates WHERE promotion_status='shadow_promoted' AND created_at >= ? ORDER BY created_at DESC",
            (since,),
        ).fetchall()
    else:
        promos = []
        shadows = []

    if not promos:
        promos = conn.execute("SELECT * FROM promotions ORDER BY id DESC LIMIT 10").fetchall()
        scope = "historical_fallback"
    else:
        scope = "run_window"

    full_audits = [audit_single_promotion(conn, dict(p)) for p in promos]
    top_rejected = conn.execute(
        """SELECT candidate_id, score_total, rejection_reason, promotion_status, generation
           FROM candidates WHERE status='rejected' ORDER BY score_total DESC LIMIT 20"""
    ).fetchall()
    conn.close()

    shadow_list = [dict(r) for r in shadows] if shadows else []
    proof_fail = sum(1 for r in top_rejected if "proof" in str(r["rejection_reason"] or ""))
    arena_fail = sum(1 for r in top_rejected if "arena" in str(r["rejection_reason"] or ""))

    if proof_fail > arena_fail and proof_fail > 5:
        gate_verdict = "proof_density_bottleneck"
    elif arena_fail > proof_fail and arena_fail > 5:
        gate_verdict = "arena_support_bottleneck"
    elif not promos and not shadows and len(top_rejected) > 10:
        gate_verdict = "promotion_gate_too_strict"
    elif full_audits and sum(1 for a in full_audits if a.get("verdict", "").startswith("promotion_weak")) > len(full_audits) // 2:
        gate_verdict = "promotion_gate_too_loose"
    else:
        gate_verdict = "promotion_gate_correct_with_notes"

    return {
        "scope": scope,
        "gate_verdict": gate_verdict,
        "full_promotions_audited": len(full_audits),
        "shadow_promotions_in_run": len(shadow_list),
        "top_rejected_audited": len(top_rejected),
        "full_promotions": full_audits,
        "shadow_promotions": shadow_list[:20],
        "top_rejected": [dict(r) for r in top_rejected],
        "proof_density_failures_top20": proof_fail,
        "arena_support_failures_top20": arena_fail,
    }


def main() -> None:
    since = None
    if RUN_JSON.exists():
        since = json.loads(RUN_JSON.read_text(encoding="utf-8")).get("run_start")
    result = audit_run(since=since)
    cls = "B1094_PROMOTION_SHADOW_AUDIT_PASS_WITH_NOTES"
    if result["gate_verdict"] in ("promotion_gate_too_strict", "proof_density_bottleneck", "arena_support_bottleneck"):
        cls = "B1094_PROMOTION_SHADOW_AUDIT_GATE_ADJUSTMENT_RECOMMENDED"
    out = {"classification": cls, **result}
    TWELVE_HOUR_RUN_DIR.mkdir(parents=True, exist_ok=True)
    (TWELVE_HOUR_RUN_DIR / "b1094_promotion_shadow_audit.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    (TWELVE_HOUR_RUN_DIR / "B1094_PROMOTION_SHADOW_AUDIT.md").write_text(
        f"# B1094 Promotion Audit\n\nGate verdict: `{result['gate_verdict']}`\n", encoding="utf-8"
    )
    print(json.dumps({"classification": cls, "gate_verdict": result["gate_verdict"]}, indent=2))


if __name__ == "__main__":
    main()
