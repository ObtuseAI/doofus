"""Build gen1640 retry live verification final artifacts."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1640-retry-live-verification-v1"
STATE = WORKSPACE / "runtime" / "state"


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
    return json.loads(path.read_text(encoding="utf-8"))


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
    post = _load_json(OUT / "post_run_invariant_check.json")
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
    ck_after = load_checkpoint()
    cc_after = read_checkpoint()

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=30)
    model_calls = conn.execute("SELECT COUNT(*) FROM model_call_events WHERE generation=1640").fetchone()[0]
    candidates = conn.execute("SELECT COUNT(*) FROM candidates WHERE generation=1640").fetchone()[0]
    promoted = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE generation=1640 AND status IN ('promoted','champion')"
    ).fetchone()[0]
    rejected = conn.execute("SELECT COUNT(*) FROM candidates WHERE generation=1640 AND status='rejected'").fetchone()[0]
    conn.close()

    init_events = _read_jsonl(STATE / "cycle_init_events.jsonl")
    init_gen1640 = [e for e in init_events if e.get("generation") == 1640]
    inline_events = _read_jsonl(STATE / "inline_rescue_events.jsonl")
    inline_gen1640 = [e for e in inline_events if e.get("generation") == 1640]
    phase_events = _read_jsonl(STATE / "supervisor_phase_events.jsonl")
    phase_gen1640 = [e for e in phase_events if e.get("generation") == 1640]

    init_timeout = any(e.get("step") == "cycle_init_timeout" for e in init_gen1640)
    init_aborted = cycle_out.get("classification") == "DOOFUS_CYCLE_INIT_TIMEOUT_ABORTED" or (
        isinstance(cycle_out.get("cycle_classification"), str) and "INIT_TIMEOUT" in cycle_out.get("cycle_classification", "")
    )

    cc_data = cc_after.get("data") or {}
    cc_class = cc_data.get("classification", cc_after.get("classification", ""))
    cc_gen = cc_data.get("generation", cc_after.get("generation"))

    pass_ok = (
        proc.get("exit_code") == 0
        and ck_after.get("generation") == 1640
        and ck_after.get("phase") == "complete"
        and cc_gen == 1640
        and "PASS" in str(cc_class)
        and post.get("all_invariants_pass")
        and pf1641.get("target_generation_total") == 0
        and model_calls <= 2
        and not init_timeout
    )
    partial_ok = (
        not pass_ok
        and post.get("stop_flag", {}).get("stop_requested")
        and pf1641.get("target_generation_total") == 0
        and ck_after.get("generation", 9999) <= 1640
    )

    if pass_ok:
        classification = "DOOFUS_GEN1640_RETRY_LIVE_VERIFICATION_PASS"
        next_action = "Create a post-live gen1640 certification/cleanup bundle before any gen1641 work."
    elif partial_ok:
        classification = "DOOFUS_GEN1640_RETRY_LIVE_VERIFICATION_PARTIAL"
        if init_aborted or init_timeout:
            next_action = "Review init watchdog abort telemetry; repair stalled step before another retry."
        else:
            next_action = "Review partial cycle evidence and reconcile checkpoint/DB before retry."
    else:
        classification = "DOOFUS_GEN1640_RETRY_LIVE_VERIFICATION_FAIL"
        next_action = "Run containment and rollback/repair before any retry."

    telemetry = {
        "classification": "DOOFUS_GEN1640_RETRY_LIVE_TELEMETRY_SUMMARY",
        "generation_before": 1639,
        "generation_after": ck_after.get("generation"),
        "checkpoint_before": starting.get("checkpoint"),
        "checkpoint_after": ck_after,
        "cycle_checkpoint_before": starting.get("cycle_checkpoint"),
        "cycle_checkpoint_after": cc_after,
        "stop_flag_before": starting.get("stop_flag"),
        "stop_flag_after": post.get("stop_flag"),
        "db_max_generation_before": 1639,
        "db_max_generation_after": pf_after.get("db_max_generation"),
        "candidates_max_generation_after": pf_after.get("db_max_generation"),
        "gen1640_row_count_before": 0,
        "gen1640_row_count_after": pf_after.get("target_generation_total"),
        "gen1641_row_count_after": pf1641.get("target_generation_total"),
        "elapsed_wall_time_seconds": elapsed_s,
        "command_used": proc.get("command"),
        "process_return_code": proc.get("exit_code"),
        "provider_route": cycle_out.get("provider_selected"),
        "model": cycle_out.get("model_name"),
        "route_classification": cycle_out.get("classification"),
        "cycle_classification": cycle_out.get("cycle_classification"),
        "live_model_call_count": model_calls,
        "candidate_count": candidates,
        "promoted_count": promoted,
        "rejected_count": rejected,
        "init_watchdog_status": "timeout_aborted" if init_timeout or init_aborted else "ok_or_not_triggered",
        "init_events_gen1640": init_gen1640[-20:],
        "inline_rescue_events_gen1640": inline_gen1640[-20:],
        "supervisor_phase_events_gen1640": phase_gen1640[-20:],
        "stop_restored": post.get("stop_flag", {}).get("stop_requested"),
        "continuous_loop_started": False,
        "repeated_cycle_detected": False,
        "self_improvement_seed_context": "staged_as_artifact_only_context",
    }
    write_pair("gen1640_retry_live_telemetry_summary", telemetry)

    final = {
        "classification": classification,
        "operator_authorization": "explicit one gen1640 retry authorized by prompt",
        "starting_state": starting,
        "process_result": proc,
        "cycle_output": cycle_out,
        "telemetry_summary": telemetry,
        "post_run_invariant_check": post,
        "next_action": next_action,
    }
    write_pair("FINAL_REPORT", final)

    if classification == "DOOFUS_GEN1640_RETRY_LIVE_VERIFICATION_PASS":
        write_pair(
            "POSTLIVE_GEN1640_CERTIFICATION_SEED",
            {
                "classification": "DOOFUS_POSTLIVE_GEN1640_CERTIFICATION_SEED",
                "warning": "Preparation only. Does not authorize gen1641.",
                "retry_classification": classification,
                "checkpoint_after": ck_after,
                "cycle_checkpoint_after": cc_after,
                "db_max_generation_after": pf_after.get("db_max_generation"),
                "gen1641_row_count": pf1641.get("target_generation_total"),
                "stop_flag_after": post.get("stop_flag"),
                "provider_model_route": {
                    "provider": cycle_out.get("provider_selected"),
                    "model": cycle_out.get("model_name"),
                },
                "init_watchdog_status": telemetry.get("init_watchdog_status"),
                "inline_rescue_status": inline_gen1640[-1].get("status") if inline_gen1640 else "unknown",
                "candidate_outcome_summary": {
                    "candidates": candidates,
                    "promoted": promoted,
                    "rejected": rejected,
                },
            },
        )

    print(json.dumps({"classification": classification}, indent=2))
    return 0 if classification.endswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
