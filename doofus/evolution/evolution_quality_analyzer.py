"""Evolution quality analysis for 12-hour run."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from doofus.core.doofus_paths import METRICS_DB, TWELVE_HOUR_RUN_DIR
from doofus.core.doofus_state import init_db
from doofus.reports.burn_in_metrics_snapshot import load_snapshot

BASELINE = TWELVE_HOUR_RUN_DIR / "b1090_pre_run_readiness_audit.json"


def analyze(*, since: str | None = None) -> dict:
    init_db()
    baseline = load_snapshot(BASELINE) if BASELINE.exists() else {}
    conn = sqlite3.connect(METRICS_DB, timeout=5.0)
    if since:
        rows = conn.execute(
            "SELECT score_total, rejection_reason, promotion_status, generation FROM candidates WHERE created_at >= ?",
            (since,),
        ).fetchall()
        rej_reasons = conn.execute(
            "SELECT reason, COUNT(*) FROM rejections WHERE created_at >= ? GROUP BY reason",
            (since,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT score_total, rejection_reason, promotion_status, generation FROM candidates").fetchall()
        rej_reasons = conn.execute("SELECT reason, COUNT(*) FROM rejections GROUP BY reason").fetchall()
    conn.close()

    scores = [float(r[0] or 0) for r in rows]
    avg = sum(scores) / len(scores) if scores else 0
    best = max(scores) if scores else 0
    base_best = float(baseline.get("best_ever_score") or 0)
    base_avg = 0.0
    shadow = sum(1 for r in rows if r[2] == "shadow_promoted")
    promoted = sum(1 for r in rows if r[2] == "promoted")
    proof_rej = sum(c for r, c in rej_reasons if "proof" in str(r).lower())
    arena_rej = sum(c for r, c in rej_reasons if "arena" in str(r).lower())

    if best > base_best + 0.01:
        verdict = "evolution_improving_with_notes" if promoted == 0 and shadow == 0 else "evolution_improving"
    elif avg <= base_avg + 0.001 and len(rows) > 50:
        verdict = "evolution_stagnating" if proof_rej > arena_rej else "evolution_generating_noise"
    elif proof_rej > promoted + shadow and proof_rej > 10:
        verdict = "evolution_gate_too_strict"
    else:
        verdict = "evolution_improving_with_notes"

    if proof_rej > arena_rej * 2 and proof_rej > 5:
        verdict = "evolution_needs_more_proof_density"
    if arena_rej > proof_rej and arena_rej > 5:
        verdict = "evolution_needs_more_arena_support"

    return {
        "verdict": verdict,
        "candidates_analyzed": len(rows),
        "avg_score": round(avg, 4),
        "best_score_in_window": round(best, 4),
        "best_ever_delta": round(best - base_best, 4),
        "shadow_promotions_in_window": shadow,
        "full_promotions_in_window": promoted,
        "rejection_reasons": {str(r): c for r, c in rej_reasons[:15]},
        "proof_density_rejections": proof_rej,
        "arena_support_rejections": arena_rej,
        "pressure_recommendation": "maintain" if verdict.startswith("evolution_improving") else "review_gate_or_generator",
    }


def main() -> None:
    run_path = TWELVE_HOUR_RUN_DIR / "b1091_12_hour_unattended_run.json"
    since = None
    if run_path.exists():
        since = json.loads(run_path.read_text(encoding="utf-8")).get("run_start")
    result = analyze(since=since)
    out = {"classification": "B1093_EVOLUTION_QUALITY_ANALYSIS_PASS_WITH_NOTES", **result}
    TWELVE_HOUR_RUN_DIR.mkdir(parents=True, exist_ok=True)
    (TWELVE_HOUR_RUN_DIR / "b1093_evolution_quality_analysis.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (TWELVE_HOUR_RUN_DIR / "B1093_EVOLUTION_QUALITY_ANALYSIS.md").write_text(
        f"# B1093 Evolution Quality\n\nVerdict: `{result['verdict']}`\n", encoding="utf-8"
    )
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
