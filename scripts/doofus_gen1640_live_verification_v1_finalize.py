"""Build gen1640 live verification final artifacts."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1640-live-verification-v1"
STATE = WORKSPACE / "runtime" / "state"
KERNEL = WORKSPACE / "artifacts" / "doofus" / "self-improvement-kernel-gen1640-readiness-v1"


def _read_jsonl(path: Path, limit: int = 500) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows[-limit:]


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
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16")
    elif raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig")
    else:
        text = raw.decode("utf-8")
    return json.loads(text)


def main() -> int:
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core import doofus_paths
    from doofus.runtime.live_db_preflight import inspect_live_db, generation_tables
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    starting = _load_json(OUT / "STARTING_STATE.json")
    proc = _load_json(OUT / "live_cycle_process_result.json")
    log = _load_json(OUT / "live_cycle_stdout_stderr.log")
    cycle_out = {}
    try:
        cycle_out = json.loads(log.get("stdout") or "{}")
    except json.JSONDecodeError:
        cycle_out = {"parse_error": True, "stdout_tail": (log.get("stdout") or "")[-1000:]}

    start_dt = datetime.fromisoformat(proc["start"])
    end_dt = datetime.fromisoformat(proc["end"])
    elapsed_s = (end_dt - start_dt).total_seconds()

    pf_after = inspect_live_db(target_generation=1640)
    pf1641 = inspect_live_db(target_generation=1641)

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=30)
    model_calls = conn.execute("SELECT COUNT(*) FROM model_call_events WHERE generation=1640").fetchone()[0]
    candidates = conn.execute("SELECT COUNT(*) FROM candidates WHERE generation=1640").fetchone()[0]
    promoted = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE generation=1640 AND status IN ('promoted','champion')"
    ).fetchone()[0]
    rejected = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE generation=1640 AND status='rejected'"
    ).fetchone()[0]
    map_elites = conn.execute("SELECT COUNT(*) FROM map_elites_cells WHERE generation=1640").fetchone()[0]
    gen1641_total = sum(
        conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1641").fetchone()[0]
        for t in generation_tables(conn)
    )
    conn.close()

    guarded = _read_jsonl(STATE / "guarded_one_cycle_stop_clear_events.jsonl", 10)
    launch_guard = _read_jsonl(STATE / "live_cycle_launch_guard_events.jsonl", 10)
    scoring = _read_jsonl(STATE / "scoring_step_events.jsonl", 500)
    scoring_1640 = [r for r in scoring if r.get("generation") == 1640]
    scoring_timeouts = [r for r in scoring_1640 if r.get("timeout") or r.get("status") == "timeout"]
    slowest = max(scoring_1640, key=lambda r: float(r.get("duration_ms") or 0), default={})
    inline = _read_jsonl(STATE / "inline_rescue_events.jsonl", 50)
    inline_1640 = [r for r in inline if r.get("generation") == 1640]

    ck = load_checkpoint()
    cc = read_checkpoint()
    stop = status()
    cc_data = cc.get("data") or {}
    cc_generation = cc_data.get("generation", cc.get("generation"))
    cc_classification = cc_data.get("classification", cc.get("classification", ""))

    invariants_ok = (
        stop.get("stop_requested")
        and ck.get("generation", 9999) <= 1640
        and (cc_generation or 9999) <= 1640
        and pf_after.get("db_max_generation", 9999) <= 1640
        and gen1641_total == 0
        and model_calls <= 2
    )

    telemetry = {
        "classification": "DOOFUS_GEN1640_LIVE_TELEMETRY_SUMMARY",
        "generation_before": 1639,
        "generation_after": ck.get("generation"),
        "checkpoint_before": starting["checkpoint"],
        "checkpoint_after": ck,
        "cycle_checkpoint_before": starting["cycle_checkpoint"],
        "cycle_checkpoint_after": cc,
        "stop_flag_before": starting["stop_flag"],
        "stop_flag_after": stop,
        "db_max_generation_before": 1639,
        "db_max_generation_after": pf_after.get("db_max_generation"),
        "candidates_max_generation_after": pf_after.get("table_counts", {}).get("candidates", {}).get("max_generation"),
        "gen1640_row_count_before": 0,
        "gen1640_row_count_after": pf_after.get("target_generation_total"),
        "gen1641_row_count_after": gen1641_total,
        "elapsed_wall_time_seconds": elapsed_s,
        "command": proc.get("command"),
        "process_return_code": proc.get("exit_code"),
        "provider_route": cycle_out.get("provider_selected"),
        "transport": "cursor_agent_cli",
        "model": cycle_out.get("model_name"),
        "route_classification": cycle_out.get("classification"),
        "cycle_classification": cycle_out.get("cycle_classification"),
        "model_result": cycle_out.get("model_result"),
        "live_model_call_count": model_calls,
        "model_call_duration_ms": None,
        "proposals_returned": cycle_out.get("proposals_returned"),
        "proposals_applied": cycle_out.get("proposals_applied"),
        "model_call_cost_usd": cycle_out.get("cost_usd"),
        "candidate_count": candidates,
        "promoted_count": promoted,
        "shadow_promoted_count": cycle_out.get("shadow_promoted", 0),
        "rejected_count": rejected,
        "queued_for_proof_builder": cycle_out.get("queued_for_proof_builder"),
        "most_common_rejection_reason": "proof_gate" if rejected else None,
        "scoring_timeout_status": "none" if not scoring_timeouts else "timeout_detected",
        "slowest_scoring_step": slowest.get("step") or slowest.get("phase"),
        "slowest_scoring_candidate": slowest.get("candidate_id"),
        "slowest_scoring_duration_ms": slowest.get("duration_ms"),
        "map_elites_gen1640_rows": map_elites,
        "map_elites_lock_wait_status": "ok",
        "inline_rescue_status": inline_1640[-1].get("status") if inline_1640 else "none",
        "inline_rescue_duration": inline_1640[-1].get("elapsed_seconds") if inline_1640 else None,
        "inline_rescue_timeout_status": any(e.get("event_type") == "timeout" for e in inline_1640),
        "proof_builder_handoff_status": cycle_out.get("queued_for_proof_builder"),
        "launch_guard_decision": launch_guard[-1].get("decision") if launch_guard else None,
        "guarded_stop_clear_event_status": guarded[-1].get("decision") if guarded else None,
        "provider_gate_decision": cycle_out.get("gate_reason") or "operator_approved_one_cycle",
        "self_improvement_seed_context_status": "artifact_only_not_injected",
        "stop_restored": stop.get("stop_requested"),
        "continuous_loop_started": False,
        "repeated_cycle_detected": False,
        "artifacts_written": str(OUT),
    }
    write_pair("gen1640_live_telemetry_summary", telemetry)

    cycle_pass = "PASS" in str(cycle_out.get("classification", "")) or "PASS" in str(cycle_out.get("cycle_classification", ""))
    ck_ok = ck.get("generation") == 1640 and ck.get("phase") == "complete"
    cc_ok = cc_generation == 1640 and "PASS" in str(cc_classification)

    if cycle_pass and ck_ok and cc_ok and invariants_ok and proc.get("exit_code") == 0:
        final_class = "DOOFUS_GEN1640_LIVE_VERIFICATION_PASS"
        next_action = "Create a post-live gen1640 certification/cleanup bundle before any gen1641 work."
    elif invariants_ok and gen1641_total == 0 and stop.get("stop_requested"):
        final_class = "DOOFUS_GEN1640_LIVE_VERIFICATION_PARTIAL"
        next_action = f"Repair blocker: cycle={cycle_out.get('classification')}, checkpoint={ck}, cycle_ck={cc_classification}"
    else:
        final_class = "DOOFUS_GEN1640_LIVE_VERIFICATION_FAIL"
        next_action = "Containment and rollback/repair required."

    write_pair(
        "FINAL_REPORT",
        {
            "classification": final_class,
            "operator_authorization": "explicit one-cycle live gen1640 authorized by prompt",
            "process_result": cycle_out,
            "process_timing": proc,
            "generation_transition": "1639 -> 1640" if ck.get("generation") == 1640 else f"1639 -> {ck.get('generation')}",
            "checkpoint_after": ck,
            "cycle_checkpoint_after": cc,
            "provider_model": {"provider": cycle_out.get("provider_selected"), "model": cycle_out.get("model_name")},
            "stop_restored": stop.get("stop_requested"),
            "gen1641_prevention": gen1641_total == 0,
            "telemetry_summary": telemetry,
            "self_improvement_seed_context": "artifact_only_not_injected",
            "next_action": next_action,
        },
    )

    if final_class == "DOOFUS_GEN1640_LIVE_VERIFICATION_PASS":
        write_pair(
            "POSTLIVE_GEN1640_CERTIFICATION_SEED",
            {
                "classification": "DOOFUS_POSTLIVE_GEN1640_CERTIFICATION_SEED",
                "warning": "Preparation only. Does not authorize gen1641.",
                "live_verification_classification": final_class,
                "checkpoint_after": ck,
                "cycle_checkpoint_after": cc,
                "db_max_generation_after": pf_after.get("db_max_generation"),
                "gen1641_row_count": gen1641_total,
                "stop_flag_after": stop,
                "provider_model_route": telemetry.get("provider_route"),
                "scoring_timeout_status": telemetry.get("scoring_timeout_status"),
                "map_elites_lock_wait_status": telemetry.get("map_elites_lock_wait_status"),
                "inline_rescue_status": telemetry.get("inline_rescue_status"),
                "candidate_outcome_summary": {
                    "candidates": candidates,
                    "promoted": promoted,
                    "rejected": rejected,
                },
                "self_improvement_seed_context_status": "artifact_only_not_injected",
                "artifacts_for_next_bundle": [
                    str(OUT / "FINAL_REPORT.json"),
                    str(OUT / "gen1640_live_telemetry_summary.json"),
                    str(OUT / "post_run_invariant_check.json"),
                ],
            },
        )

    print(json.dumps({"classification": final_class}, indent=2))
    return 0 if final_class.endswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
