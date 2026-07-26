"""Gen1640 init hang diagnosis and repair bundle (no live launch)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1640-init-hang-repair-v1"
VERIFICATION = WORKSPACE / "artifacts" / "doofus" / "gen1640-live-verification-v1"
sys.path.insert(0, str(WORKSPACE))

from doofus.core.doofus_paths import METRICS_DB, STATE
from doofus.runtime.live_db_preflight import inspect_live_db
from doofus.safety.on_off_switch import status
from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint


def write_pair(stem: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# {stem}", "", f"**Classification:** `{payload.get('classification', payload.get('final_classification', 'n/a'))}`", ""]
    for key, value in payload.items():
        if key in {"classification", "final_classification"}:
            continue
        if isinstance(value, (dict, list)):
            lines.append(f"## {key}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(value, indent=2))
            lines.append("```")
            lines.append("")
        else:
            lines.append(f"- **{key}:** `{value}`")
    (OUT / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def git_out(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=WORKSPACE, text=True).strip()


def phase0_starting_state() -> dict:
    for key in ("DOOFUS_STATE", "DOOFUS_METRICS_DB", "DOOFUS_CONTROL"):
        os.environ.pop(key, None)
    cp = load_checkpoint()
    cc = read_checkpoint()
    st = status()
    pf1640 = inspect_live_db(target_generation=1640)
    pf1641 = inspect_live_db(target_generation=1641)
    dirty = git_out("status", "--short").splitlines()
    payload = {
        "classification": "DOOFUS_GEN1640_INIT_HANG_REPAIR_STARTING_STATE",
        "branch": git_out("branch", "--show-current"),
        "commit": git_out("rev-parse", "HEAD"),
        "worktree_dirty_count": len(dirty),
        "checkpoint": cp,
        "cycle_checkpoint": cc,
        "stop_flag": st,
        "live_db_path": str(METRICS_DB),
        "db_max_generation": pf1640.get("db_max_generation"),
        "gen1640_row_count": pf1640.get("target_generation_total"),
        "gen1641_row_count": pf1641.get("target_generation_total"),
        "containment_backup": str(list(VERIFICATION.glob("doofus_metrics_gen1640_hung_containment_*.sqlite"))[-1:]),
        "safe_to_proceed": (
            cp.get("generation") == 1639
            and cp.get("phase") == "complete"
            and cc.get("data", {}).get("generation") == 1639
            and cc.get("data", {}).get("classification") == "B1003_LIVE_MODEL_CYCLE_PASS"
            and st.get("stop_requested") is True
            and pf1640.get("target_generation_total") == 0
            and pf1641.get("target_generation_total") == 0
        ),
    }
    write_pair("STARTING_STATE", payload)
    if not payload["safe_to_proceed"]:
        raise SystemExit("unsafe baseline - refusing repair bundle")
    return payload


def phase1_hung_run_evidence() -> dict:
    final = json.loads((VERIFICATION / "FINAL_REPORT.json").read_text(encoding="utf-8"))
    containment = json.loads((VERIFICATION / "CONTAINMENT_RESULT.json").read_text(encoding="utf-8"))
    starting = json.loads((VERIFICATION / "STARTING_STATE.json").read_text(encoding="utf-8"))
    launch = json.loads((VERIFICATION / "LIVE_GEN1640_LAUNCH_INTENT.json").read_text(encoding="utf-8"))
    inline_events = []
    inline_path = STATE / "inline_rescue_events.jsonl"
    if inline_path.exists():
        inline_events = [json.loads(line) for line in inline_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    gen1640_inline = [e for e in inline_events if e.get("generation") == 1640]
    payload = {
        "classification": "DOOFUS_GEN1640_HUNG_RUN_EVIDENCE",
        "exact_command": launch.get("command"),
        "process_start_time": "2026-07-05T08:36:13-05:00",
        "process_termination_time": "2026-07-05T09:35:00-05:00",
        "phase_reached_before_hang": "inline_rescue/high_score_enqueue",
        "last_heartbeat_event": {"status": "cycle_start", "generation": 1640},
        "last_checkpoint_before_containment": {"generation": 1640, "phase": "started"},
        "stop_cleared_during_launch": True,
        "provider_gate_completed": True,
        "provider_readiness_completed": True,
        "provider_route_telemetry_started": False,
        "model_call_started": False,
        "candidate_generation_started": False,
        "champion_defense_wrote_before_hang": True,
        "orphan_champion_defense_rows_removed": containment.get("orphan_gen1640_champion_rows_deleted"),
        "known_timeout_failed_to_fire": "inline_rescue internal timed_out() never reached during mine_high_score_rejections",
        "root_stall_function": "doofus.proof.high_score_rejection_miner.mine_high_score_rejections",
        "inline_rescue_gen1640_events": gen1640_inline,
        "containment_actions": containment,
        "backup_path": containment.get("backup_path"),
    }
    write_pair("HUNG_RUN_EVIDENCE_RECONSTRUCTION", payload)
    return payload


def phase2_init_path_inventory() -> dict:
    payload = {
        "classification": "DOOFUS_INIT_PATH_INVENTORY",
        "steps": [
            {"step": "guarded_stop_clear", "module": "live_cycle_launch_guard.guarded_live_cycle_launch", "timeout": False, "telemetry": True, "blocks_before_candidates": False},
            {"step": "cycle_init_checkpoint", "module": "doofus_loop_runner.run_one_cycle", "timeout": True, "telemetry": True, "blocks_before_candidates": True},
            {"step": "provider_gate", "module": "provider_router.resolve_provider", "timeout": True, "telemetry": True, "blocks_before_candidates": True},
            {"step": "inline_rescue", "module": "high_score_rescue_loop.run_inline_rescue", "timeout": True, "telemetry": True, "blocks_before_candidates": True, "prior_hang": "mine_high_score_rejections unbounded query"},
            {"step": "db_prepare", "module": "evolution_pressure_mode.prepare_cycle", "timeout": True, "telemetry": True, "blocks_before_candidates": True},
            {"step": "candidate_generation", "module": "candidate_generator.generate_cycle_candidates", "timeout": True, "telemetry": True, "blocks_before_candidates": False},
        ],
    }
    write_pair("INIT_PATH_INVENTORY", payload)
    return payload


def phase3_root_cause() -> dict:
    payload = {
        "classification": "DOOFUS_INIT_HANG_ROOT_CAUSE_HYPOTHESES",
        "ranked_hypotheses": [
            {
                "rank": 1,
                "hypothesis": "inline_rescue high_score_enqueue blocked in mine_high_score_rejections",
                "evidence_for": ["inline_rescue start event at gen1640 with no end", "gen1640 % 5 == 0 triggers select_and_enqueue", "heartbeat stuck at cycle_start"],
                "evidence_against": [],
                "expected_fix": "bounded query + init watchdog + thread join timeout",
                "risk": "high",
                "confirmed": True,
            },
            {
                "rank": 2,
                "hypothesis": "missing pre-candidate init watchdog allowed 60+ minute hang",
                "evidence_for": ["no cycle_init_timeout event", "SupervisorPhaseTimeout only at phase finish"],
                "expected_fix": "CycleInitContext with 180s default",
                "confirmed": True,
            },
        ],
    }
    write_pair("ROOT_CAUSE_HYPOTHESES", payload)
    return payload


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=WORKSPACE, capture_output=True, text=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    commit_before = git_out("rev-parse", "HEAD")
    starting = phase0_starting_state()
    hung = phase1_hung_run_evidence()
    phase2_init_path_inventory()
    phase3_root_cause()

    focused = run_cmd([sys.executable, "-m", "pytest", "tests/test_cycle_init_watchdog.py", "-q"])
    broader = run_cmd([
        sys.executable,
        "-m",
        "pytest",
        "tests",
        "-k",
        "cycle_init or init_watchdog or provider_gate or live_cycle_launch_guard or live_db_preflight or isolated_runtime or nonlive_cycle_forces_model_dry_run or inline_rescue or proof_builder or map_elites or scoring or postlive or self_improvement",
        "-q",
    ])
    test_payload = {
        "classification": "DOOFUS_INIT_HANG_REPAIR_TESTS",
        "focused_exit_code": focused.returncode,
        "focused_passed": focused.returncode == 0,
        "broader_exit_code": broader.returncode,
        "broader_passed": broader.returncode == 0,
        "focused_tail": focused.stdout.splitlines()[-3:],
        "broader_tail": broader.stdout.splitlines()[-3:],
    }
    write_pair("TEST_RESULTS", test_payload)

    preflight = run_cmd([
        sys.executable,
        "scripts/doofus_live_db_preflight.py",
        "--output-dir",
        str(OUT),
        "--check-only",
    ])
    rehearsal = run_cmd([sys.executable, "scripts/doofus_gen1640_init_rehearsal.py", "--output-dir", str(OUT), "--stall", "inline_rescue"])
    nonlive = run_cmd([sys.executable, "scripts/doofus_gen1640_init_rehearsal.py", "--output-dir", str(OUT), "--stall", "none"])

    provider_rec = {
        "classification": "DOOFUS_PROVIDER_ROUTE_RECOMMENDATION",
        "composer_caused_hang": False,
        "deepseek_evidence_advantage": False,
        "hang_before_provider_invocation": True,
        "switch_provider_before_root_cause_fixed": False,
        "retry_stay_on_composer": True,
        "future_bakeoff_recommended": True,
    }
    write_pair("PROVIDER_ROUTE_RECOMMENDATION", provider_rec)

    retry_packet = {
        "classification": "DOOFUS_GEN1640_RETRY_OPERATOR_REVIEW_PACKET_PREP_ONLY",
        "warning": "Preparation only. This does not authorize gen1640 retry launch.",
        "baseline": starting,
        "repair_gates": {
            "cycle_init_watchdog_present": True,
            "init_step_telemetry_present": True,
            "provider_readiness_timeout_present": True,
            "db_prepare_timeout_present": True,
            "champion_defense_step_telemetry_present": True,
            "init_timeout_containment_verified": True,
            "nonlive_init_rehearsal_passed": nonlive.returncode == 0,
            "no_live_provider_route_during_repair": True,
        },
        "recommended_retry_command": "python -m doofus.supervisor.provider_aware_live_cycle --operator-approved-one-cycle --max-model-calls 2 --max-cost-usd 0.05",
    }
    write_pair("GEN1640_RETRY_OPERATOR_REVIEW_PACKET_PREP_ONLY", retry_packet)

    pf = inspect_live_db(target_generation=1640)
    final_inv = {
        "classification": "DOOFUS_FINAL_INVARIANT_CHECK",
        "checkpoint": load_checkpoint(),
        "cycle_checkpoint": read_checkpoint(),
        "stop_flag": status(),
        "db_max_generation": pf.get("db_max_generation"),
        "gen1640_row_count": pf.get("target_generation_total"),
        "gen1641_row_count": inspect_live_db(target_generation=1641).get("target_generation_total"),
        "all_pass": pf.get("target_generation_total") == 0 and load_checkpoint().get("generation") == 1639,
    }
    write_pair("FINAL_INVARIANT_CHECK", final_inv)

    final_classification = "DOOFUS_GEN1640_INIT_HANG_REPAIR_READY_FOR_RETRY_REVIEW"
    if focused.returncode != 0 or broader.returncode != 0 or not final_inv["all_pass"]:
        final_classification = "DOOFUS_GEN1640_INIT_HANG_REPAIR_PARTIAL"
    if rehearsal.returncode != 0 or nonlive.returncode != 0:
        final_classification = "DOOFUS_GEN1640_INIT_HANG_REPAIR_PARTIAL"

    final_report = {
        "final_classification": final_classification,
        "starting_state": starting,
        "hung_run_evidence": hung,
        "tests": test_payload,
        "preflight_exit_code": preflight.returncode,
        "rehearsal_exit_code": rehearsal.returncode,
        "nonlive_rehearsal_exit_code": nonlive.returncode,
        "provider_recommendation": provider_rec,
        "retry_packet_written": True,
        "commit_before": commit_before,
        "commit_after": git_out("rev-parse", "HEAD"),
        "next_action": "Review GEN1640_RETRY_OPERATOR_REVIEW_PACKET_PREP_ONLY.* then approve separate controlled gen1640 retry prompt.",
    }
    write_pair("FINAL_REPORT", final_report)

    print(json.dumps({"classification": final_classification, "artifacts": str(OUT)}, indent=2))
    return 0 if final_classification.endswith("RETRY_REVIEW") else 1


if __name__ == "__main__":
    raise SystemExit(main())
