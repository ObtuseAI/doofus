"""Strict full functionality verdict."""
from __future__ import annotations

import json

from doofus.core.doofus_paths import RUNTIME_CLOSURE_DIR
from doofus.reports.burn_in_metrics_snapshot import load_snapshot, capture_metrics_snapshot
from doofus.runtime.runtime_health import get_runtime_health


def build_verdict() -> dict:
    baseline = load_snapshot(RUNTIME_CLOSURE_DIR / "b1130_pre_runtime_closure_audit.json")
    validation = {}
    vpath = RUNTIME_CLOSURE_DIR / "b1137_short_live_full_function_validation.json"
    if vpath.exists():
        validation = json.loads(vpath.read_text(encoding="utf-8"))
    post = capture_metrics_snapshot(label="b1138")
    health = get_runtime_health()

    cand_d = int(post.get("candidate_count", 0)) - int(baseline.get("candidate_count", 0))
    mut_d = int(post.get("mutation_rows", 0)) - int(baseline.get("mutation_rows", 0))
    rej_d = int(post.get("rejection_count", 0)) - int(baseline.get("rejection_count", 0))
    promo_d = int(post.get("promotion_count", 0)) - int(baseline.get("promotion_count", 0))
    shadow_d = int(post.get("shadow_promotion_count", 0)) - int(baseline.get("shadow_promotion_count", 0))

    hb_age = health["supervisor"].get("heartbeat_age_seconds")
    dash_ok = health["dashboard"].get("reachable") is True
    sup_ok = health["supervisor"].get("process_alive") is True
    watch_ok = health["watchdog"].get("active") is True
    mgr_ok = health["runtime_manager"].get("active") is True
    hb_fresh = hb_age is not None and hb_age < 180

    checks = {
        "supervisor_alive": sup_ok,
        "heartbeat_fresh": hb_fresh,
        "dashboard_reachable": dash_ok,
        "watchdog_active_or_registered": watch_ok,
        "runtime_manager_active": mgr_ok,
        "candidate_delta_positive": cand_d > 0,
        "mutation_delta_positive": mut_d > 0,
        "evolution_delta": rej_d > 0 or promo_d > 0 or shadow_d > 0,
        "may_run": post.get("may_run") is True,
        "no_emergency": not post.get("emergency_stop"),
    }

    if all(checks.values()):
        verdict = "fully_functional"
    elif dash_ok and hb_fresh and sup_ok and cand_d > 0 and mut_d > 0:
        verdict = "fully_functional_with_notes"
    elif not dash_ok:
        verdict = "not_fully_functional_dashboard_dead"
    elif not hb_fresh or not sup_ok:
        verdict = "not_fully_functional_supervisor_stale"
    elif not watch_ok and not mgr_ok:
        verdict = "not_fully_functional_watchdog_missing"
    elif cand_d <= 0:
        verdict = "not_fully_functional_no_evolution_delta"
    else:
        verdict = "not_fully_functional_runtime_blocked"

    return {
        "verdict": verdict,
        "checks": checks,
        "deltas": {"candidate": cand_d, "mutation": mut_d, "rejection": rej_d, "promotion": promo_d, "shadow": shadow_d},
        "health": health,
        "validation_classification": validation.get("classification"),
    }


def main() -> None:
    RUNTIME_CLOSURE_DIR.mkdir(parents=True, exist_ok=True)
    result = build_verdict()
    cls = "B1138_FINAL_FUNCTIONALITY_VERDICT_PASS" if result["verdict"].startswith("fully_functional") else "B1138_FINAL_FUNCTIONALITY_VERDICT_BLOCKED"
    if result["verdict"] == "fully_functional_with_notes":
        cls = "B1138_FINAL_FUNCTIONALITY_VERDICT_PASS_WITH_NOTES"
    out = {"classification": cls, **result}
    (RUNTIME_CLOSURE_DIR / "b1138_final_functionality_verdict.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
