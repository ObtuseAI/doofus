"""Post 12-hour run metrics delta."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.core.doofus_paths import TWELVE_HOUR_RUN_DIR
from doofus.reports.burn_in_metrics_snapshot import capture_metrics_snapshot, load_snapshot, save_snapshot

BASELINE = TWELVE_HOUR_RUN_DIR / "b1090_pre_run_readiness_audit.json"
RUN_JSON = TWELVE_HOUR_RUN_DIR / "b1091_12_hour_unattended_run.json"
OUT_JSON = TWELVE_HOUR_RUN_DIR / "b1092_post_run_metrics_delta.json"
OUT_MD = TWELVE_HOUR_RUN_DIR / "B1092_POST_RUN_METRICS_DELTA.md"


def _d(a: dict, b: dict, k: str):
    va, vb = a.get(k, 0) or 0, b.get(k, 0) or 0
    if isinstance(va, float) or isinstance(vb, float):
        return round(float(vb) - float(va), 4)
    return int(vb) - int(va)


def build_report() -> dict:
    baseline = load_snapshot(BASELINE)
    post = capture_metrics_snapshot(label="post_12h")
    run = json.loads(RUN_JSON.read_text(encoding="utf-8")) if RUN_JSON.exists() else {}
    cps = run.get("checkpoints", [])
    expected = run.get("duration_seconds", 43200) // run.get("checkpoint_interval", 1800)
    deltas = {k: _d(baseline, post, k) for k in (
        "model_call_count", "successful_live_calls", "estimated_cost", "candidate_count",
        "promotion_count", "shadow_promotion_count", "rejection_count", "lineage_rows",
        "mutation_rows", "arena_result_rows", "elite_archive_count", "best_ever_score",
        "challenger_tournament_count", "retired_branch_count", "proof_debt_count", "arena_debt_count",
        "safety_event_count", "rate_limit_events_total", "cooldown_events_total",
    )}
    deltas["model_calls"] = deltas.pop("model_call_count")
    report = {
        "classification": "B1092_POST_RUN_METRICS_DELTA_PASS_WITH_NOTES",
        "baseline": baseline,
        "post": post,
        "deltas": deltas,
        "checkpoint_count": len(cps),
        "expected_checkpoints": expected,
        "missed_checkpoints": max(0, expected - len(cps)),
        "run_start": run.get("run_start"),
        "run_end": run.get("run_end"),
        "runtime_duration_seconds": run.get("actual_duration_seconds"),
    }
    save_snapshot(OUT_JSON, report)
    OUT_MD.write_text(
        f"# B1092 Post-Run Metrics Delta\n\nClassification: `{report['classification']}`\n\n"
        f"Checkpoints: {len(cps)}/{expected}\n\n"
        + "\n".join(f"- {k}: {v}" for k, v in deltas.items()),
        encoding="utf-8",
    )
    return report


def main() -> None:
    r = build_report()
    print(json.dumps({"classification": r["classification"], "deltas": r["deltas"]}, indent=2))


if __name__ == "__main__":
    main()
