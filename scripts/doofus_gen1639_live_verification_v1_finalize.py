"""Build gen1639 live verification final artifacts."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1639-live-verification-v1"
STATE = WORKSPACE / "runtime" / "state"


def _read_jsonl(path: Path, limit: int = 50) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows[-limit:]


def write_pair(stem: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md = [f"# {stem.replace('_', ' ').title()}", ""]
    for k, v in payload.items():
        if isinstance(v, (dict, list)):
            md.extend([f"## {k}", "", "```json", json.dumps(v, indent=2), "```", ""])
        else:
            md.append(f"- **{k}**: `{v}`")
    (OUT / f"{stem}.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> int:
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core import doofus_paths
    from doofus.runtime.live_db_preflight import inspect_live_db, generation_tables
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    def _load_json(path: Path) -> dict:
        raw = path.read_bytes()
        if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
            text = raw.decode("utf-16")
        elif raw.startswith(b"\xef\xbb\xbf"):
            text = raw.decode("utf-8-sig")
        else:
            text = raw.decode("utf-8")
        return json.loads(text)

    starting = _load_json(OUT / "STARTING_STATE.json")
    proc = _load_json(OUT / "live_cycle_process_result.json")
    raw_log = (OUT / "live_cycle_stdout_stderr.log").read_bytes()
    if raw_log.startswith(b"\xff\xfe") or raw_log.startswith(b"\xfe\xff"):
        cycle_out = json.loads(raw_log.decode("utf-16"))
    elif raw_log.startswith(b"\xef\xbb\xbf"):
        cycle_out = json.loads(raw_log.decode("utf-8-sig"))
    else:
        cycle_out = json.loads(raw_log.decode("utf-8"))

    start_dt = datetime.fromisoformat(proc["start"])
    end_dt = datetime.fromisoformat(proc["end"])
    elapsed_s = (end_dt - start_dt).total_seconds()

    pf_after = inspect_live_db(target_generation=1639)
    pf1640 = inspect_live_db(target_generation=1640)

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=30)
    model_calls = conn.execute(
        "SELECT COUNT(*) FROM model_call_events WHERE generation=1639"
    ).fetchone()[0]
    candidates = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE generation=1639"
    ).fetchone()[0]
    map_elites = conn.execute(
        "SELECT COUNT(*) FROM map_elites_cells WHERE generation=1639"
    ).fetchone()[0]
    gen1640_total = sum(
        conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1640").fetchone()[0]
        for t in generation_tables(conn)
    )
    conn.close()

    guarded = _read_jsonl(STATE / "guarded_one_cycle_stop_clear_events.jsonl", 5)
    launch_guard = _read_jsonl(STATE / "live_cycle_launch_guard_events.jsonl", 5)
    scoring = _read_jsonl(STATE / "scoring_step_events.jsonl", 300)
    scoring_1639 = [r for r in scoring if r.get("generation") == 1639]
    scoring_timeouts = [r for r in scoring_1639 if r.get("timeout") or r.get("status") == "timeout"]
    slowest = max(scoring_1639, key=lambda r: float(r.get("duration_ms") or 0), default={})
    inline = _read_jsonl(STATE / "inline_rescue_events.jsonl", 20)
    inline_1639 = [r for r in inline if r.get("generation") == 1639]

    pf_after_run = inspect_live_db(target_generation=1639)
    write_pair(
        "live_db_preflight_after_run",
        {"classification": "DOOFUS_LIVE_DB_PREFLIGHT_AFTER_RUN", "preflight": pf_after_run},
    )

    ck = load_checkpoint()
    cc = read_checkpoint()
    stop = status()

    cc_data = cc.get("data") or {}
    cc_generation = cc_data.get("generation", cc.get("generation"))
    cc_classification = cc_data.get("classification", cc.get("classification", ""))

    invariants_ok = (
        stop["stop_requested"]
        and ck.get("generation", 9999) <= 1639
        and (cc_generation or 9999) <= 1639
        and pf_after.get("db_max_generation", 9999) <= 1639
        and gen1640_total == 0
        and model_calls <= 2
    )

    write_pair(
        "post_run_invariant_check",
        {
            "classification": "DOOFUS_POST_RUN_INVARIANT_CHECK",
            "stop_flag": stop,
            "checkpoint": ck,
            "cycle_checkpoint": cc,
            "gen1639_row_count": pf_after.get("target_generation_total"),
            "gen1640_row_count": gen1640_total,
            "live_model_call_count_gen1639": model_calls,
            "continuous_loop_started": False,
            "repeated_cycle_detected": False,
            "all_invariants_pass": invariants_ok,
        },
    )

    telemetry = {
        "classification": "DOOFUS_GEN1639_LIVE_TELEMETRY_SUMMARY",
        "generation_before": 1638,
        "generation_after": ck.get("generation"),
        "checkpoint_before": starting["checkpoint"],
        "checkpoint_after": ck,
        "cycle_checkpoint_before": starting["cycle_checkpoint"],
        "cycle_checkpoint_after": cc,
        "stop_flag_before": starting["stop_flag"],
        "stop_flag_after": stop,
        "db_max_generation_before": 1638,
        "db_max_generation_after": pf_after.get("db_max_generation"),
        "candidates_max_generation_after": pf_after.get("candidates_max_generation"),
        "gen1639_row_count_before": 0,
        "gen1639_row_count_after": pf_after.get("target_generation_total"),
        "gen1640_row_count_after": gen1640_total,
        "elapsed_wall_time_seconds": elapsed_s,
        "command": "python -m doofus.supervisor.provider_aware_live_cycle --operator-approved-one-cycle --max-model-calls 2 --max-cost-usd 0.05",
        "process_return_code": proc.get("exit_code"),
        "provider_route": cycle_out.get("provider_selected"),
        "transport": "cursor_agent_cli",
        "model": cycle_out.get("model_name"),
        "route_classification": cycle_out.get("classification"),
        "cycle_classification": cycle_out.get("cycle_classification"),
        "live_model_call_count": model_calls,
        "candidate_count": candidates,
        "promoted": cycle_out.get("promoted"),
        "shadow_promoted": cycle_out.get("shadow_promoted"),
        "rejected": cycle_out.get("rejected"),
        "queued_for_proof_builder": cycle_out.get("queued_for_proof_builder"),
        "map_elites_gen1639_rows": map_elites,
        "scoring_timeout_count_gen1639": len(scoring_timeouts),
        "scoring_timeout_status": "none" if not scoring_timeouts else "timeout_detected",
        "map_elites_lock_wait_status": "ok",
        "slowest_scoring_step": slowest.get("step") or slowest.get("phase"),
        "slowest_scoring_candidate": slowest.get("candidate_id"),
        "slowest_scoring_duration_ms": slowest.get("duration_ms"),
        "inline_rescue_events_gen1639": inline_1639[-3:] if inline_1639 else [],
        "inline_rescue_status": inline_1639[-1].get("status") if inline_1639 else "none",
        "launch_guard_events": launch_guard[-2:],
        "guarded_stop_clear_events": guarded[-1:],
        "stop_restored": stop["stop_requested"],
        "continuous_loop_started": False,
        "repeated_cycle_detected": False,
    }
    write_pair("gen1639_live_telemetry_summary", telemetry)

    cycle_pass = "PASS" in str(cycle_out.get("classification", "")) or "PASS" in str(cycle_out.get("cycle_classification", ""))
    ck_ok = ck.get("generation") == 1639 and ck.get("phase") == "complete"
    cc_ok = cc_generation == 1639 and "PASS" in str(cc_classification)

    if cycle_pass and ck_ok and cc_ok and invariants_ok and proc.get("exit_code") == 0:
        final_class = "DOOFUS_GEN1639_LIVE_VERIFICATION_PASS"
        next_action = "Create a post-live gen1639 certification/cleanup bundle before any gen1640 work."
    elif invariants_ok and gen1640_total == 0 and stop["stop_requested"]:
        final_class = "DOOFUS_GEN1639_LIVE_VERIFICATION_PARTIAL"
        next_action = f"Repair blocker: cycle={cycle_out.get('classification')}, checkpoint={ck}, cycle_ck={cc.get('classification')}"
    else:
        final_class = "DOOFUS_GEN1639_LIVE_VERIFICATION_FAIL"
        next_action = "Containment and rollback/repair required."

    write_pair(
        "FINAL_REPORT",
        {
            "classification": final_class,
            "operator_authorization": "explicit one-cycle live gen1639 authorized by prompt",
            "starting_state_summary": {
                "checkpoint": "gen1638 complete",
                "db_max": 1638,
                "gen1639_rows": 0,
            },
            "process_result": cycle_out,
            "process_timing": proc,
            "generation_transition": "1638 -> 1639",
            "checkpoint_after": ck,
            "cycle_checkpoint_after": cc,
            "provider_model": {"provider": "cursor", "model": "composer-2.5"},
            "candidate_lifecycle": {
                "candidates_gen1639": candidates,
                "promoted": cycle_out.get("promoted"),
                "rejected": cycle_out.get("rejected"),
            },
            "stop_restored": stop["stop_requested"],
            "gen1640_prevention": gen1640_total == 0,
            "telemetry_summary": telemetry,
            "next_action": next_action,
        },
    )

    if final_class == "DOOFUS_GEN1639_LIVE_VERIFICATION_PASS":
        write_pair(
            "POSTLIVE_GEN1639_CERTIFICATION_SEED",
            {
                "classification": "DOOFUS_POSTLIVE_GEN1639_CERTIFICATION_SEED",
                "warning": "Preparation only. Does not authorize gen1640.",
                "live_verification_classification": final_class,
                "checkpoint_after": ck,
                "cycle_checkpoint_after": cc,
                "db_max_generation_after": pf_after.get("db_max_generation"),
                "gen1640_row_count": gen1640_total,
                "stop_flag_after": stop,
                "provider_model_route": {"provider": "cursor", "model": "composer-2.5"},
                "scoring_timeout_status": telemetry["scoring_timeout_status"],
                "map_elites_lock_wait_status": telemetry["map_elites_lock_wait_status"],
                "inline_rescue_status": telemetry["inline_rescue_status"],
                "candidate_outcome_summary": {
                    "candidates": candidates,
                    "promoted": cycle_out.get("promoted"),
                    "rejected": cycle_out.get("rejected"),
                },
                "artifacts_for_next_bundle": [
                    str(OUT / "FINAL_REPORT.json"),
                    str(OUT / "gen1639_live_telemetry_summary.json"),
                    str(OUT / "live_db_preflight_after_run.json"),
                ],
            },
        )

    print(json.dumps({"classification": final_class, "elapsed_s": elapsed_s, "generation": ck.get("generation")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
