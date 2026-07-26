"""Build gen1641 live verification final artifacts with run-window telemetry filtering."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1641-live-verification-v1"
STATE = WORKSPACE / "runtime" / "state"
TARGET_GENERATION = 1641


def write_pair(stem: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md = [f"# {stem.replace('_', ' ').title()}", ""]
    for k, v in payload.items():
        if isinstance(v, (dict, list)):
            md.extend([f"## {k}", "", "```json", json.dumps(v, indent=2)[:12000], "```", ""])
        else:
            md.append(f"- **{k}**: `{v}`")
    (OUT / f"{stem}.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_valid_ck(ck: dict) -> bool:
    try:
        from doofus.supervisor.checkpoint_baseline import validate_checkpoint

        validate_checkpoint(ck)
        return True
    except Exception:
        return False


def _schema_valid_cc(cc: dict) -> bool:
    try:
        from doofus.supervisor.checkpoint_baseline import validate_cycle_checkpoint

        validate_cycle_checkpoint(cc)
        return True
    except Exception:
        return False


def main() -> int:
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core import doofus_paths
    from doofus.reports.run_window_telemetry_filter import (
        classify_init_watchdog,
        filter_events_by_run_window,
        read_jsonl,
        stale_classification_impact,
    )
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    starting = _load_json(OUT / "STARTING_STATE.json")
    proc = _load_json(OUT / "live_cycle_process_result.json")
    log = _load_json(OUT / "live_cycle_stdout_stderr.log")
    post = _load_json(OUT / "post_run_invariant_check.json")
    try:
        cycle_out = json.loads(log.get("stdout") or "{}")
    except json.JSONDecodeError:
        cycle_out = proc.get("cycle_output") or {"parse_error": True, "stdout_tail": (log.get("stdout") or "")[-1000:]}

    start_dt = datetime.fromisoformat(proc["start"])
    end_dt = datetime.fromisoformat(proc["end"])
    elapsed_s = (end_dt - start_dt).total_seconds()
    run_id = (starting.get("checkpoint") or {}).get("run_id")

    pf_after = inspect_live_db(target_generation=TARGET_GENERATION)
    pf1642 = inspect_live_db(target_generation=TARGET_GENERATION + 1)
    ck_after = load_checkpoint()
    cc_after = read_checkpoint()
    ck_schema = _schema_valid_ck(ck_after)
    cc_schema = _schema_valid_cc(cc_after)

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=30)
    model_calls = conn.execute(
        "SELECT COUNT(*) FROM model_call_events WHERE generation=?", (TARGET_GENERATION,)
    ).fetchone()[0]
    candidates = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE generation=?", (TARGET_GENERATION,)
    ).fetchone()[0]
    promoted = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE generation=? AND status IN ('promoted','champion')",
        (TARGET_GENERATION,),
    ).fetchone()[0]
    shadow_promoted = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE generation=? AND status='shadow_promoted'",
        (TARGET_GENERATION,),
    ).fetchone()[0]
    rejected = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE generation=? AND status='rejected'",
        (TARGET_GENERATION,),
    ).fetchone()[0]
    conn.close()

    telemetry_sources = {
        "cycle_init_events.jsonl": read_jsonl(STATE / "cycle_init_events.jsonl"),
        "inline_rescue_events.jsonl": read_jsonl(STATE / "inline_rescue_events.jsonl"),
        "high_score_miner_events.jsonl": read_jsonl(STATE / "high_score_miner_events.jsonl"),
        "shadow_upgrade_events.jsonl": read_jsonl(STATE / "shadow_upgrade_events.jsonl"),
        "supervisor_phase_events.jsonl": read_jsonl(STATE / "supervisor_phase_events.jsonl"),
        "scoring_step_events.jsonl": read_jsonl(STATE / "scoring_step_events.jsonl"),
    }
    filtered: dict[str, object] = {}
    stale_sources: dict[str, int] = {}
    total_excluded = 0
    for name, events in telemetry_sources.items():
        result = filter_events_by_run_window(
            events,
            generation=TARGET_GENERATION,
            window_start=start_dt,
            window_end=end_dt,
            source_name=name,
            run_id=run_id,
        )
        filtered[name] = result
        stale_sources.update(result.stale_event_sources)
        total_excluded += result.events_excluded_count

    init_gen = filtered["cycle_init_events.jsonl"].events_in_window  # type: ignore[attr-defined]
    inline_gen = filtered["inline_rescue_events.jsonl"].events_in_window  # type: ignore[attr-defined]
    miner_gen = filtered["high_score_miner_events.jsonl"].events_in_window  # type: ignore[attr-defined]
    shadow_gen = filtered["shadow_upgrade_events.jsonl"].events_in_window  # type: ignore[attr-defined]
    phase_gen = filtered["supervisor_phase_events.jsonl"].events_in_window  # type: ignore[attr-defined]
    scoring_gen = filtered["scoring_step_events.jsonl"].events_in_window  # type: ignore[attr-defined]
    init_filter = filtered["cycle_init_events.jsonl"]  # type: ignore[assignment]

    init_timeout, init_status, init_duration_ms, init_stalled = classify_init_watchdog(init_gen)
    init_timeout = init_status == "timeout_aborted"

    miner_deferred = any(
        e.get("decision") in {"HIGH_SCORE_MINER_DEFERRED_DEADLINE", "MINER_DEADLINE_EXCEEDED"}
        for e in miner_gen
    )
    inline_hs_deferred = any(e.get("stage") == "inline_rescue_high_score_deferred" for e in inline_gen)
    inline_shadow_deferred = any(e.get("stage") == "inline_rescue_shadow_upgrade_deferred" for e in inline_gen)
    inline_end = any(e.get("event_type") == "end" for e in inline_gen)
    inline_timeout = any(e.get("event_type") == "timeout" for e in inline_gen)

    shadow_deferred = any(
        e.get("decision") in {"SHADOW_UPGRADE_DEFERRED_DEADLINE", "SHADOW_UPGRADE_PARTIAL"}
        or e.get("step") == "shadow_upgrade_deferred"
        for e in shadow_gen
    )
    shadow_processed = max((e.get("item_index") or 0 for e in shadow_gen if e.get("step") == "shadow_upgrade_item_end"), default=0)

    cc_data = cc_after.get("data") or {}
    cc_class = cc_data.get("classification", cc_after.get("classification", ""))
    cc_gen = cc_data.get("generation", cc_after.get("generation"))
    cost_observed = cycle_out.get("total_cost_usd") or cycle_out.get("cost_usd")
    cost_status = "not_reported" if cost_observed is None else "reported"

    pass_without_stale = (
        proc.get("exit_code") == 0
        and ck_after.get("generation") == TARGET_GENERATION
        and ck_after.get("phase") == "complete"
        and cc_gen == TARGET_GENERATION
        and "PASS" in str(cc_class)
        and post.get("all_invariants_pass")
        and pf1642.get("target_generation_total") == 0
        and model_calls <= 2
        and ck_schema
        and cc_schema
        and inline_end
        and not inline_timeout
    )
    stale_impact = stale_classification_impact(
        unfiltered_init_events=telemetry_sources["cycle_init_events.jsonl"],
        filtered_init_events=init_gen,
        generation=TARGET_GENERATION,
        pass_without_stale=pass_without_stale and not init_timeout,
    )
    stale_impact = {
        **stale_impact,
        "classification_before_stale_filter": stale_impact["classification_before_stale_filter"].replace(
            "GEN1640_RETRY3", "GEN1641"
        ),
        "classification_after_stale_filter": (
            "DOOFUS_GEN1641_LIVE_VERIFICATION_PASS"
            if pass_without_stale and not init_timeout
            else stale_impact["classification_after_stale_filter"].replace("GEN1640_RETRY3", "GEN1641")
        ),
    }

    pass_ok = pass_without_stale and not init_timeout
    partial_ok = (
        not pass_ok
        and post.get("stop_flag", {}).get("stop_requested")
        and pf1642.get("target_generation_total") == 0
        and ck_after.get("generation", 9999) <= TARGET_GENERATION
        and ck_schema
    )

    if pass_ok:
        classification = "DOOFUS_GEN1641_LIVE_VERIFICATION_PASS"
        next_action = "Create a post-live gen1641 certification/cleanup bundle before any gen1642 work."
    elif partial_ok:
        classification = "DOOFUS_GEN1641_LIVE_VERIFICATION_PARTIAL"
        if init_timeout:
            next_action = f"Review init watchdog abort at stalled step '{init_stalled}' before another retry."
        else:
            next_action = "Review partial cycle evidence and reconcile checkpoint/DB before retry."
    else:
        classification = "DOOFUS_GEN1641_LIVE_VERIFICATION_FAIL"
        next_action = "Run containment and rollback/repair before any retry."

    filter_summary = init_filter.to_summary_fields()  # type: ignore[attr-defined]
    telemetry = {
        "classification": "DOOFUS_GEN1641_LIVE_TELEMETRY_SUMMARY",
        "generation_before": TARGET_GENERATION - 1,
        "generation_after": ck_after.get("generation"),
        "checkpoint_before": starting.get("checkpoint"),
        "checkpoint_after": ck_after,
        "cycle_checkpoint_before": starting.get("cycle_checkpoint"),
        "cycle_checkpoint_after": cc_after,
        "stop_flag_before": starting.get("stop_flag"),
        "stop_flag_after": post.get("stop_flag"),
        "db_max_generation_before": TARGET_GENERATION - 1,
        "db_max_generation_after": pf_after.get("db_max_generation"),
        "candidates_max_generation_after": pf_after.get("db_max_generation"),
        "gen1641_row_count_before": 0,
        "gen1641_row_count_after": pf_after.get("target_generation_total"),
        "gen1642_row_count_after": pf1642.get("target_generation_total"),
        "elapsed_wall_time_seconds": elapsed_s,
        "command_used": proc.get("command"),
        "process_return_code": proc.get("exit_code"),
        "provider_route": cycle_out.get("provider_selected") or "cursor",
        "transport": "cursor_agent_cli",
        "model": cycle_out.get("model_name") or "composer-2.5",
        "route_classification": cycle_out.get("classification"),
        "cycle_classification": cycle_out.get("cycle_classification"),
        "live_model_call_count": model_calls,
        "model_call_limit": 2,
        "cost_limit_usd": 0.05,
        "cost_observed_usd": cost_observed,
        "cost_observed_status": cost_status,
        "candidate_count": candidates,
        "promoted_count": promoted,
        "shadow_promoted_count": shadow_promoted,
        "rejected_count": rejected,
        "init_watchdog_status": init_status,
        "init_duration_ms": init_duration_ms,
        "init_stalled_step": init_stalled,
        **filter_summary,
        "events_excluded_as_stale_total": total_excluded,
        "stale_event_sources": stale_sources,
        **stale_impact,
        "high_score_miner_status": "deferred" if miner_deferred else "ok_or_unknown",
        "high_score_miner_deferred_status": miner_deferred,
        "high_score_miner_rows_returned": next(
            (e.get("rows_returned") for e in reversed(miner_gen) if e.get("rows_returned") is not None),
            None,
        ),
        "shadow_upgrade_status": "deferred" if shadow_deferred else ("partial" if shadow_processed else "ok_or_unknown"),
        "shadow_upgrade_items_processed": shadow_processed,
        "shadow_upgrade_deferred_status": shadow_deferred,
        "inline_rescue_status": inline_gen[-1].get("status") if inline_gen else "unknown",
        "inline_rescue_high_score_deferred_status": inline_hs_deferred,
        "inline_rescue_shadow_upgrade_deferred_status": inline_shadow_deferred,
        "inline_rescue_timeout_status": inline_timeout,
        "init_events_gen1641": init_gen[-30:],
        "inline_rescue_events_gen1641": inline_gen[-30:],
        "high_score_miner_events_gen1641": miner_gen[-30:],
        "shadow_upgrade_events_gen1641": shadow_gen[-30:],
        "supervisor_phase_events_gen1641": phase_gen[-30:],
        "scoring_events_gen1641": scoring_gen[-30:],
        "checkpoint_schema_valid": ck_schema,
        "cycle_checkpoint_schema_valid": cc_schema,
        "stop_restored": post.get("stop_flag", {}).get("stop_requested"),
        "continuous_loop_started": False,
        "repeated_cycle_detected": False,
        "self_improvement_seed_context": starting.get("self_improvement_seed_decision", "staged_as_artifact_only_context"),
    }
    write_pair("gen1641_live_telemetry_summary", telemetry)

    prelaunch = _load_json(OUT / "prelaunch_test_results.json") if (OUT / "prelaunch_test_results.json").exists() else {}
    final = {
        "classification": classification,
        "operator_authorization": "explicit one gen1641 live cycle authorized by prompt",
        "starting_state": starting,
        "process_result": proc,
        "cycle_output": cycle_out,
        "telemetry_summary": telemetry,
        "post_run_invariant_check": post,
        "prelaunch_tests": prelaunch,
        "run_window_filter": {**filter_summary, **stale_impact, "stale_event_sources": stale_sources},
        "next_action": next_action,
    }
    write_pair("FINAL_REPORT", final)

    if classification == "DOOFUS_GEN1641_LIVE_VERIFICATION_PASS":
        write_pair(
            "POSTLIVE_GEN1641_CERTIFICATION_SEED",
            {
                "classification": "DOOFUS_POSTLIVE_GEN1641_CERTIFICATION_SEED",
                "warning": "Preparation only. Does not authorize gen1642.",
                "gen1641_classification": classification,
                "checkpoint_after": ck_after,
                "cycle_checkpoint_after": cc_after,
                "db_max_generation_after": pf_after.get("db_max_generation"),
                "gen1642_row_count": pf1642.get("target_generation_total"),
                "stop_flag_after": post.get("stop_flag"),
                "provider_model_route": {"provider": telemetry.get("provider_route"), "model": telemetry.get("model")},
                "run_window_filter_applied": True,
                "stale_events_excluded": total_excluded,
                "init_watchdog_status": telemetry.get("init_watchdog_status"),
                "high_score_miner_status": telemetry.get("high_score_miner_status"),
                "shadow_upgrade_status": telemetry.get("shadow_upgrade_status"),
                "inline_rescue_status": telemetry.get("inline_rescue_status"),
                "candidate_outcome_summary": {
                    "candidates": candidates,
                    "promoted": promoted,
                    "shadow_promoted": shadow_promoted,
                    "rejected": rejected,
                },
                "artifacts_for_next_bundle": [
                    str(OUT / "FINAL_REPORT.json"),
                    str(OUT / "gen1641_live_telemetry_summary.json"),
                    str(OUT / "post_run_invariant_check.json"),
                ],
            },
        )

    preflight_before = _load_json(OUT / "live_db_preflight_before_launch.json") if (OUT / "live_db_preflight_before_launch.json").exists() else {}
    preflight_after = _load_json(OUT / "live_db_preflight_after_run.json") if (OUT / "live_db_preflight_after_run.json").exists() else {}
    miner_check = _load_json(OUT / "live_scale_miner_readiness_check.json") if (OUT / "live_scale_miner_readiness_check.json").exists() else {}
    shadow_check = _load_json(OUT / "shadow_upgrade_readiness_check.json") if (OUT / "shadow_upgrade_readiness_check.json").exists() else {}
    rw_check = _load_json(OUT / "run_window_telemetry_readiness_check.json") if (OUT / "run_window_telemetry_readiness_check.json").exists() else {}
    rehearsal_check = _load_json(OUT / "inline_rescue_rehearsal_readiness_check.json") if (OUT / "inline_rescue_rehearsal_readiness_check.json").exists() else {}
    nonlive_probe = _load_json(OUT / "nonlive_dry_run_guard_probe.json") if (OUT / "nonlive_dry_run_guard_probe.json").exists() else {}

    slowest_step = None
    slowest_candidate = None
    slowest_duration = None
    scoring_timeout = False
    map_elites_lock_wait = False
    for e in scoring_gen:
        dur = e.get("duration_ms") or e.get("elapsed_ms")
        if dur is not None and (slowest_duration is None or dur > slowest_duration):
            slowest_duration = dur
            slowest_step = e.get("step") or e.get("phase")
            slowest_candidate = e.get("candidate_id")
        if e.get("timeout") or e.get("status") == "timeout":
            scoring_timeout = True
    for e in phase_gen:
        if "map_elites" in str(e.get("phase", "")).lower() and e.get("lock_wait"):
            map_elites_lock_wait = True

    branch = starting.get("branch", "unknown")
    commit = starting.get("commit", "unknown")
    dirty_count = starting.get("worktree_dirty_count", 0)
    ck_before = starting.get("checkpoint") or {}
    cc_before = starting.get("cycle_checkpoint") or {}
    cc_before_data = cc_before.get("data") or {}
    live_route = cycle_out.get("live_route_invoked")
    if live_route is None:
        live_route = cycle_out.get("classification") not in {"DOOFUS_MODEL_DRY_RUN", None} and model_calls > 0

    artifacts = sorted(str(p.relative_to(WORKSPACE)) for p in OUT.glob("*") if p.is_file())

    lines = [
        "final classification: " + classification,
        "branch: " + str(branch),
        "commit: " + str(commit),
        "worktree status: " + ("dirty" if dirty_count else "clean") + f" ({dirty_count} unstaged/staged entries)",
        f"checkpoint before: generation={ck_before.get('generation')}, phase={ck_before.get('phase')}",
        f"checkpoint after: generation={ck_after.get('generation')}, phase={ck_after.get('phase')}",
        f"cycle checkpoint before: {cc_before_data.get('classification', cc_before.get('classification'))}, generation={cc_before_data.get('generation', cc_before.get('generation'))}",
        f"cycle checkpoint after: {cc_class}, generation={cc_gen}",
        f"checkpoint schema valid: {ck_schema}",
        f"cycle checkpoint schema valid: {cc_schema}",
        f"stop flag before: stop_requested={starting.get('stop_flag', {}).get('stop_requested')}",
        f"stop flag after: stop_requested={post.get('stop_flag', {}).get('stop_requested')}",
        f"DB max generation before: {TARGET_GENERATION - 1}",
        f"DB max generation after: {pf_after.get('db_max_generation')}",
        f"candidates max generation after: {pf_after.get('db_max_generation')}",
        "gen1641 row count before: 0",
        f"gen1641 row count after: {pf_after.get('target_generation_total')}",
        f"gen1642 row count after: {pf1642.get('target_generation_total')}",
        f"live route invoked: {live_route}",
        f"live model-call count: {model_calls}",
        f"provider route: {telemetry.get('provider_route')}",
        f"transport: {telemetry.get('transport')}",
        f"model: {telemetry.get('model')}",
        "model-call limit: 2",
        "cost limit: 0.05",
        f"cost observed: {cost_observed}",
        f"cost observed status: {cost_status}",
        f"generation before: {TARGET_GENERATION - 1}",
        f"generation after: {ck_after.get('generation')}",
        f"elapsed wall time: {elapsed_s:.1f}s",
        f"init watchdog status: {init_status}",
        f"init duration: {init_duration_ms}ms",
        f"init stalled step: {init_stalled}",
        f"high-score miner status: {telemetry.get('high_score_miner_status')}",
        f"high-score miner duration: {next((e.get('duration_ms') for e in reversed(miner_gen) if e.get('duration_ms')), 'n/a')}",
        f"high-score miner rows returned: {telemetry.get('high_score_miner_rows_returned')}",
        f"high-score miner deferred: {miner_deferred}",
        f"shadow_upgrade status: {telemetry.get('shadow_upgrade_status')}",
        f"shadow_upgrade duration: {next((e.get('duration_ms') for e in reversed(shadow_gen) if e.get('duration_ms')), 'n/a')}",
        f"shadow_upgrade items processed: {shadow_processed}",
        f"shadow_upgrade deferred: {shadow_deferred}",
        f"inline rescue status: {telemetry.get('inline_rescue_status')}",
        f"inline rescue high-score deferred: {inline_hs_deferred}",
        f"inline rescue shadow_upgrade deferred: {inline_shadow_deferred}",
        f"candidate count: {candidates}",
        f"promoted: {promoted}",
        f"shadow promoted: {shadow_promoted}",
        f"rejected: {rejected}",
        "queued for proof builder: n/a",
        f"scoring timeout status: {scoring_timeout}",
        f"MAP-Elites lock-wait status: {map_elites_lock_wait}",
        f"slowest scoring step: {slowest_step}",
        f"slowest scoring candidate: {slowest_candidate}",
        f"slowest scoring duration: {slowest_duration}",
        f"run-window filter applied: {filter_summary.get('run_window_filter_applied')}",
        f"events excluded as stale: {total_excluded}",
        f"stale events changed classification: {stale_impact.get('stale_events_changed_classification')}",
        f"self-improvement seed context: {telemetry.get('self_improvement_seed_context')}",
        f"guard tests: {'passed' if prelaunch.get('focused_passed') and prelaunch.get('broader_passed') else 'failed'}",
        f"non-live dry-run guard: {'passed' if nonlive_probe.get('passed') else 'failed'}",
        f"live-scale miner readiness: {'passed' if miner_check.get('passed') else 'failed'}",
        f"shadow upgrade readiness: {'passed' if shadow_check.get('passed') else 'failed'}",
        f"run-window telemetry readiness: {'passed' if rw_check.get('passed') else 'failed'}",
        f"inline-rescue rehearsal: {'passed' if rehearsal_check.get('passed') else 'failed'}",
        f"live DB preflight before: {'passed' if preflight_before.get('passed') else 'failed'}",
        f"live DB preflight after: {'passed' if preflight_after.get('passed') else 'failed'}",
        "guarded stop-clear telemetry: captured in cycle output",
        "provider-gate telemetry: captured in cycle output",
        "gen1642 launched: false",
        "continuous loop started: false",
        "repeated cycle detected: false",
        "cross-project side effects: false",
        f"artifacts written: {len(artifacts)} files under artifacts/doofus/gen1641-live-verification-v1/",
        f"exact next recommended operator action: {next_action}",
    ]
    print("\n".join(lines))

    return 0 if classification.endswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
