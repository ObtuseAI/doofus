"""Aggressive tuning verdict report."""
from __future__ import annotations

import json

from doofus.core.doofus_paths import PROOF_BUILDER_TUNING_DIR, STATE
from doofus.proof.proof_builder_queue import queue_summary
from doofus.evolution.shadow_elite_archive import get_shadow_elite_archive
from doofus.reports.burn_in_metrics_snapshot import load_snapshot, capture_metrics_snapshot


def build_verdict() -> dict:
    baseline_path = PROOF_BUILDER_TUNING_DIR / "b1100_pre_tuning_audit.json"
    run_path = PROOF_BUILDER_TUNING_DIR / "b1105_60_min_aggressive_conversion_run.json"
    baseline = load_snapshot(baseline_path) if baseline_path.exists() else {}
    post = capture_metrics_snapshot(label="b1106_post")
    run = json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else {}
    q = queue_summary()
    se = get_shadow_elite_archive()
    promo_delta = int(post.get("promotion_count") or 0) - int(baseline.get("promotion_count") or 0)
    shadow_delta = int(post.get("shadow_promotion_count") or 0) - int(baseline.get("shadow_promotion_count") or 0)
    best_delta = float(post.get("best_ever_score") or 0) - float(baseline.get("best_ever_score") or 0)

    if promo_delta > 0:
        verdict = "tuning_correct_full_promotion_seen"
    elif shadow_delta > 0 or se.get("shadow_elite_count", 0) >= 5:
        verdict = "tuning_correct_shadow_elites_seen"
    elif q.get("successes", 0) > 0:
        verdict = "proof_builder_working_gate_still_strict"
    elif q.get("entries_total", 0) >= 20:
        verdict = "proof_generation_still_bottleneck"
    else:
        verdict = "threshold_correct_proof_builder_weak"

    sweep_path = PROOF_BUILDER_TUNING_DIR / "b1104_threshold_sweep_tuning.json"
    threshold_changed = False
    threshold_after = 0.55
    if sweep_path.exists():
        sw = json.loads(sweep_path.read_text(encoding="utf-8"))
        threshold_after = sw.get("recommended_threshold") or sw.get("current_threshold") or 0.55
        threshold_changed = sw.get("recommended_threshold") is not None

    return {
        "verdict": verdict,
        "promotion_delta": promo_delta,
        "shadow_promotion_delta": shadow_delta,
        "shadow_elite_count": se.get("shadow_elite_count", 0),
        "proof_builder": q,
        "best_ever_delta": round(best_delta, 4),
        "threshold_changed": threshold_changed,
        "proof_density_threshold_after": threshold_after,
        "run_checkpoints": len(run.get("checkpoints", [])),
    }


def main() -> None:
    PROOF_BUILDER_TUNING_DIR.mkdir(parents=True, exist_ok=True)
    result = build_verdict()
    cls = "B1106_CONVERSION_ANALYSIS_PASS_WITH_NOTES"
    if result["verdict"] == "tuning_correct_full_promotion_seen":
        cls = "B1106_CONVERSION_ANALYSIS_PASS"
    out = {"classification": cls, **result}
    (PROOF_BUILDER_TUNING_DIR / "b1106_conversion_analysis.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (PROOF_BUILDER_TUNING_DIR / "B1106_CONVERSION_ANALYSIS.md").write_text(f"# B1106 Verdict: `{result['verdict']}`\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
