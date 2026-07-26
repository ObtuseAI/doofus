"""Post burn-in metrics delta report."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.reports.burn_in_metrics_snapshot import (
    AUDIT_DIR,
    capture_metrics_snapshot,
    load_snapshot,
    save_snapshot,
)

BASELINE_JSON = AUDIT_DIR / "b1070_pre_burn_in_audit.json"
DELTA_JSON = AUDIT_DIR / "b1072_post_burn_in_metrics_delta.json"
DELTA_MD = AUDIT_DIR / "B1072_POST_BURN_IN_METRICS_DELTA.md"


def _delta(a: dict, b: dict, key: str) -> int | float:
    va = a.get(key, 0) or 0
    vb = b.get(key, 0) or 0
    if isinstance(va, float) or isinstance(vb, float):
        return round(float(vb) - float(va), 4)
    return int(vb) - int(va)


def compute_delta(baseline: dict, post: dict, *, burn_in_start: str | None = None, burn_in_end: str | None = None) -> dict:
    duration_seconds = None
    if burn_in_start and burn_in_end:
        try:
            from datetime import datetime

            t0 = datetime.fromisoformat(burn_in_start.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(burn_in_end.replace("Z", "+00:00"))
            duration_seconds = int((t1 - t0).total_seconds())
        except Exception:
            pass

    deltas = {
        "runtime_duration_seconds": duration_seconds,
        "model_calls": _delta(baseline, post, "model_call_count"),
        "successful_live_calls": _delta(baseline, post, "successful_live_calls"),
        "estimated_cost": _delta(baseline, post, "estimated_cost"),
        "candidate_delta": _delta(baseline, post, "candidate_count"),
        "promotion_delta": _delta(baseline, post, "promotion_count"),
        "rejection_delta": _delta(baseline, post, "rejection_count"),
        "lineage_delta": _delta(baseline, post, "lineage_rows"),
        "mutation_delta": _delta(baseline, post, "mutation_rows"),
        "arena_result_delta": _delta(baseline, post, "arena_result_rows"),
        "safety_event_delta": _delta(baseline, post, "safety_event_count"),
        "rate_limit_events": _delta(baseline, post, "rate_limit_events_total"),
        "cooldown_events": _delta(baseline, post, "cooldown_events_total"),
        "duplicate_pid_count_post": post.get("duplicate_pid_count", 0),
        "sqlite_locked_post": post.get("sqlite", {}).get("locked", False),
    }
    classification = "B1072_POST_BURN_IN_METRICS_DELTA_PASS"
    if not post.get("may_run") and not post.get("emergency_stop"):
        classification = "B1072_POST_BURN_IN_METRICS_DELTA_PASS_WITH_NOTES"
    if post.get("sqlite", {}).get("locked"):
        classification = "B1072_POST_BURN_IN_METRICS_DELTA_BLOCKED"
    return {
        "classification": classification,
        "baseline": baseline,
        "post": post,
        "deltas": deltas,
        "burn_in_start": burn_in_start,
        "burn_in_end": burn_in_end,
    }


def build_report() -> dict:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    baseline = load_snapshot(BASELINE_JSON) if BASELINE_JSON.exists() else capture_metrics_snapshot(label="baseline_fallback")
    post = capture_metrics_snapshot(label="post_burn_in")

    burn_in_path = AUDIT_DIR / "b1071_2_5_hour_live_burn_in.json"
    burn_in_start = burn_in_end = None
    if burn_in_path.exists():
        bi = json.loads(burn_in_path.read_text(encoding="utf-8"))
        burn_in_start = bi.get("burn_in_start")
        burn_in_end = bi.get("burn_in_end")

    report = compute_delta(baseline, post, burn_in_start=burn_in_start, burn_in_end=burn_in_end)
    save_snapshot(DELTA_JSON, report)

    d = report["deltas"]
    md = f"""# B1072 Post Burn-In Metrics Delta

Classification: `{report['classification']}`

| Metric | Delta |
|--------|-------|
| Runtime (s) | {d.get('runtime_duration_seconds')} |
| Model calls | {d.get('model_calls')} |
| Live calls | {d.get('successful_live_calls')} |
| Est. cost | ${d.get('estimated_cost')} |
| Candidates | {d.get('candidate_delta')} |
| Promotions | {d.get('promotion_delta')} |
| Rejections | {d.get('rejection_delta')} |
| Lineage | {d.get('lineage_delta')} |
| Mutations | {d.get('mutation_delta')} |
| Arena results | {d.get('arena_result_delta')} |
| Safety events | {d.get('safety_event_delta')} |
| Rate limits | {d.get('rate_limit_events')} |
| Cooldowns | {d.get('cooldown_events')} |
"""
    DELTA_MD.write_text(md, encoding="utf-8")
    return report


def main() -> None:
    r = build_report()
    print(json.dumps({"classification": r["classification"], "deltas": r["deltas"]}, indent=2))


if __name__ == "__main__":
    main()
