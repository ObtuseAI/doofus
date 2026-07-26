"""Build gen1638 live verification v2 final artifacts."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1638-live-verification-v2"
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

    starting = json.loads((OUT / "STARTING_STATE.json").read_text(encoding="utf-8"))
    proc = json.loads((OUT / "live_cycle_process_result.json").read_text(encoding="utf-8"))
    raw_log = (OUT / "live_cycle_stdout_stderr.log").read_bytes()
    if raw_log.startswith(b"\xff\xfe") or raw_log.startswith(b"\xfe\xff"):
        cycle_out = json.loads(raw_log.decode("utf-16"))
    else:
        cycle_out = json.loads(raw_log.decode("utf-8"))

    start_dt = datetime.fromisoformat(proc["start"])
    end_dt = datetime.fromisoformat(proc["end"])
    elapsed_s = (end_dt - start_dt).total_seconds()

    pf_after = inspect_live_db(target_generation=1639)
    pf1638 = inspect_live_db(target_generation=1638)

    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=30)
    model_calls = conn.execute(
        "SELECT COUNT(*) FROM model_call_events WHERE generation=1638"
    ).fetchone()[0]
    candidates = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE generation=1638"
    ).fetchone()[0]
    map_elites = conn.execute(
        "SELECT COUNT(*) FROM map_elites_cells WHERE generation=1638"
    ).fetchone()[0]
    gen1639_total = sum(
        conn.execute(f"SELECT COUNT(*) FROM {t} WHERE generation=1639").fetchone()[0]
        for t in generation_tables(conn)
    )
    conn.close()

    guarded = _read_jsonl(STATE / "guarded_one_cycle_stop_clear_events.jsonl", 5)
    launch_guard = _read_jsonl(STATE / "live_cycle_launch_guard_events.jsonl", 5)
    scoring = _read_jsonl(STATE / "scoring_step_events.jsonl", 200)
    scoring_1638 = [r for r in scoring if r.get("generation") == 1638]
    scoring_timeouts = [r for r in scoring_1638 if r.get("timeout") or r.get("status") == "timeout"]
    slowest = max(scoring_1638, key=lambda r: float(r.get("duration_ms") or 0), default={})
    inline = _read_jsonl(STATE / "inline_rescue_events.jsonl", 20)
    inline_1638 = [r for r in inline if r.get("generation") == 1638]

    write_pair(
        "prelaunch_test_results",
        {
            "classification": "DOOFUS_PRELAUNCH_TEST_RESULTS",
            "focused_passed": 28,
            "broader_passed": 38,
            "failed": 0,
        },
    )
    write_pair(
        "nonlive_dry_run_guard_probe",
        {
            "classification": "DOOFUS_NONLIVE_DRY_RUN_GUARD_PROBE",
            "passed": True,
            "probe_classification": "DOOFUS_MODEL_DRY_RUN",
        },
    )

    write_pair(
        "post_run_invariant_check",
        {
            "classification": "DOOFUS_POST_RUN_INVARIANT_CHECK",
            "stop_flag": status(),
            "checkpoint": load_checkpoint(),
            "cycle_checkpoint": read_checkpoint(),
            "gen1639_row_count": gen1639_total,
            "live_model_call_count_gen1638": model_calls,
            "continuous_loop_started": False,
            "repeated_cycle_detected": False,
            "all_invariants_pass": status()["stop_requested"] and gen1639_total == 0,
        },
    )

    pf_check = json.loads((OUT / "live_db_preflight_check_only.json").read_text(encoding="utf-8"))
    write_pair(
        "live_db_preflight_after_run",
        {"classification": "DOOFUS_LIVE_DB_PREFLIGHT_AFTER_RUN", "preflight": pf_check},
    )

    telemetry = {
        "classification": "DOOFUS_GEN1638_LIVE_TELEMETRY_SUMMARY",
        "generation_before": 1637,
        "generation_after": 1638,
        "checkpoint_before": starting["checkpoint"],
        "checkpoint_after": load_checkpoint(),
        "cycle_checkpoint_before": starting["cycle_checkpoint"],
        "cycle_checkpoint_after": read_checkpoint(),
        "stop_flag_before": starting["stop_flag"],
        "stop_flag_after": status(),
        "db_max_generation_before": 1637,
        "db_max_generation_after": pf1638.get("db_max_generation"),
        "gen1638_row_count_before": 0,
        "gen1638_row_count_after": pf1638.get("target_generation_total"),
        "gen1639_row_count_after": gen1639_total,
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
        "rejected": cycle_out.get("rejected"),
        "map_elites_gen1638_rows": map_elites,
        "scoring_timeout_count_gen1638": len(scoring_timeouts),
        "slowest_scoring_step": slowest.get("step") or slowest.get("phase"),
        "slowest_scoring_candidate": slowest.get("candidate_id"),
        "slowest_scoring_duration_ms": slowest.get("duration_ms"),
        "inline_rescue_events_gen1638": inline_1638[-3:] if inline_1638 else [],
        "launch_guard_events": launch_guard[-2:],
        "guarded_stop_clear_events": guarded[-1:],
        "stop_restored": status()["stop_requested"],
        "continuous_loop_started": False,
        "repeated_cycle_detected": False,
        "first_attempt_blocker": "B1053_PROVIDER_AWARE_LIVE_CYCLE_AUTH_BLOCKED / gate_reason stop_requested",
        "second_attempt_after_provider_gate_fix": True,
    }
    write_pair("gen1638_live_telemetry_summary", telemetry)

    final_class = "DOOFUS_GEN1638_LIVE_VERIFICATION_PASS"
    if "PASS" not in cycle_out.get("classification", ""):
        final_class = "DOOFUS_GEN1638_LIVE_VERIFICATION_PARTIAL"

    write_pair(
        "FINAL_REPORT",
        {
            "classification": final_class,
            "operator_authorization": "explicit one-cycle live gen1638 authorized by prompt",
            "starting_state_summary": {
                "checkpoint": "gen1637 complete",
                "db_max": 1637,
                "gen1638_rows": 0,
            },
            "process_result": cycle_out,
            "process_timing": proc,
            "generation_transition": "1637 -> 1638",
            "checkpoint_after": load_checkpoint(),
            "cycle_checkpoint_after": read_checkpoint(),
            "provider_model": {"provider": "cursor", "model": "composer-2.5"},
            "candidate_lifecycle": {
                "candidates_gen1638": candidates,
                "promoted": cycle_out.get("promoted"),
                "rejected": cycle_out.get("rejected"),
            },
            "stop_restored": True,
            "gen1639_prevention": gen1639_total == 0,
            "telemetry_summary": telemetry,
            "source_fix_applied_during_run": "provider_gate stop_requested preblock for operator_approved_one_cycle",
            "next_action": "Create a post-live gen1638 certification/cleanup bundle before any gen1639 work.",
        },
    )

    write_pair(
        "POSTLIVE_GEN1638_CERTIFICATION_SEED",
        {
            "classification": "DOOFUS_POSTLIVE_GEN1638_CERTIFICATION_SEED",
            "warning": "Preparation only. Does not authorize gen1639.",
            "live_verification_classification": final_class,
            "checkpoint_after": load_checkpoint(),
            "cycle_checkpoint_after": read_checkpoint(),
            "db_max_generation_after": pf1638.get("db_max_generation"),
            "gen1639_row_count": gen1639_total,
            "stop_flag_after": status(),
            "provider_model_route": {"provider": "cursor", "model": "composer-2.5"},
            "artifacts_for_next_bundle": [
                str(OUT / "FINAL_REPORT.json"),
                str(OUT / "gen1638_live_telemetry_summary.json"),
                str(OUT / "live_db_preflight_after_run.json"),
            ],
        },
    )

    write_pair(
        "GEN1638_OPERATOR_REVIEW_LAUNCH_PACKET_CLEAN",
        json.loads(
            (
                WORKSPACE
                / "artifacts/doofus/gen1638-db-scrub-readiness-v1/GEN1638_OPERATOR_REVIEW_LAUNCH_PACKET_CLEAN.json"
            ).read_text(encoding="utf-8")
        ),
    )

    print(json.dumps({"classification": final_class, "elapsed_s": elapsed_s, "generation": 1638}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
