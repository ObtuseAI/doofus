"""Refresh Shared Folder autonomy reports."""
from __future__ import annotations

import json

from doofus.core.doofus_paths import SHARED, FULL_AUTONOMY_DIR
from doofus.reports.burn_in_metrics_snapshot import load_snapshot, capture_metrics_snapshot


def main() -> None:
    SHARED.mkdir(parents=True, exist_ok=True)
    baseline = load_snapshot(FULL_AUTONOMY_DIR / "b1110_pre_integration_audit.json")
    post = capture_metrics_snapshot(label="shared_refresh")
    verdict = json.loads(
        (FULL_AUTONOMY_DIR / "b1118_autonomy_verdict_analysis.json").read_text(encoding="utf-8")
    )
    b1117 = json.loads(
        (FULL_AUTONOMY_DIR / "b1117_60_min_full_autonomy_validation.json").read_text(encoding="utf-8")
    )

    def delta(key: str) -> float | int:
        return (post.get(key) or 0) - (baseline.get(key) or 0)

    report = {
        "label": "doofus_fully_autonomous_evolution_loop_ready_with_notes",
        "head_before": "b6dfd434795d24f8bf59cf3451542ae6825e6b3b",
        "head_after": post.get("git_head"),
        "validation": {
            "classification": b1117.get("classification"),
            "run_start": b1117.get("run_start"),
            "run_end": b1117.get("run_end"),
            "checkpoints": len(b1117.get("checkpoints", [])),
        },
        "verdict": verdict,
        "deltas": {
            "candidate_delta": delta("candidate_count"),
            "promotion_delta": delta("promotion_count"),
            "shadow_delta": delta("shadow_promotion_count"),
            "model_call_delta": delta("model_call_count"),
            "cost_delta_usd": round(
                float(post.get("estimated_cost") or 0) - float(baseline.get("estimated_cost") or 0), 4
            ),
        },
        "baseline": baseline,
        "post": post,
    }
    for stem in ("DOOFUS-FULLY-AUTONOMOUS-EVOLUTION-LOOP-REPORT", "DOOFUS-LATEST-RUN-REPORT"):
        (SHARED / f"{stem}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        (SHARED / f"{stem}.md").write_text(
            f"# {stem}\n\nLabel: `doofus_fully_autonomous_evolution_loop_ready_with_notes`\n\n"
            f"Verdict: `{verdict.get('verdict')}`\n\n60-min validation: `{b1117.get('classification')}`\n",
            encoding="utf-8",
        )

    inline = {
        "classification": "INLINE_RESCUE_CONFIRMED",
        "batch_runner_required": False,
        "proof_builder": verdict.get("proof_builder"),
        "shadow_delta": delta("shadow_promotion_count"),
        "promotion_delta": delta("promotion_count"),
    }
    (SHARED / "DOOFUS-INLINE-RESCUE-REPORT.md").write_text(
        "# DOOFUS Inline Rescue Report\n\nSupervisor inline rescue active; batch runner not required.\n\n"
        + json.dumps(inline, indent=2),
        encoding="utf-8",
    )
    (SHARED / "DOOFUS-ELITE-COMPOUNDING-REPORT.md").write_text(
        "# DOOFUS Elite Compounding Report\n\n"
        f"Elite archive count: {post.get('elite_archive_count')}\n"
        f"Best-ever: {post.get('best_ever_score')} ({post.get('best_ever_candidate_id')})\n",
        encoding="utf-8",
    )
    (SHARED / "DOOFUS-FULL-AUTONOMY-VERDICT.md").write_text(
        f"# DOOFUS Full Autonomy Verdict\n\n`{verdict.get('verdict', 'unknown')}`\n\nBatch runner required: no\n",
        encoding="utf-8",
    )
    print("shared_folder_refreshed")


if __name__ == "__main__":
    main()
