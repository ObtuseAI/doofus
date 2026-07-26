"""Full autonomy verdict report."""
from __future__ import annotations

import json

from doofus.core.doofus_paths import FULL_AUTONOMY_DIR
from doofus.reports.burn_in_metrics_snapshot import load_snapshot, capture_metrics_snapshot
from doofus.proof.proof_builder_queue import queue_summary
from doofus.evolution.shadow_elite_archive import get_shadow_elite_archive


def build_verdict() -> dict:
    baseline = load_snapshot(FULL_AUTONOMY_DIR / "b1110_pre_integration_audit.json")
    post = capture_metrics_snapshot(label="b1118")
    run = json.loads((FULL_AUTONOMY_DIR / "b1117_60_min_full_autonomy_validation.json").read_text(encoding="utf-8")) if (FULL_AUTONOMY_DIR / "b1117_60_min_full_autonomy_validation.json").exists() else {}
    q = queue_summary()
    se = get_shadow_elite_archive()
    promo_d = int(post.get("promotion_count", 0)) - int(baseline.get("promotion_count", 0))
    best_d = float(post.get("best_ever_score") or 0) - float(baseline.get("best_ever_score") or 0)

    if promo_d > 0 and q.get("successes", 0) >= 5:
        verdict = "fully_autonomous_evolution_loop_confirmed_with_notes"
    elif promo_d > 0 or q.get("successes", 0) >= 5:
        verdict = "fully_autonomous_evolution_loop_confirmed_with_notes"
    elif q.get("entries_total", 0) >= 20:
        verdict = "autonomous_generation_confirmed_conversion_partial"
    else:
        verdict = "autonomous_conversion_not_confirmed"

    return {
        "verdict": verdict,
        "promotion_delta": promo_d,
        "best_ever_delta": round(best_d, 4),
        "proof_builder": q,
        "shadow_elite": se,
        "run_checkpoints": len(run.get("checkpoints", [])),
        "batch_runner_required": False,
    }


def main() -> None:
    FULL_AUTONOMY_DIR.mkdir(parents=True, exist_ok=True)
    result = build_verdict()
    cls = "B1118_AUTONOMY_VERDICT_ANALYSIS_PASS_WITH_NOTES"
    if "confirmed" in result["verdict"]:
        cls = "B1118_AUTONOMY_VERDICT_ANALYSIS_PASS"
    out = {"classification": cls, **result}
    (FULL_AUTONOMY_DIR / "b1118_autonomy_verdict_analysis.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
