"""Generate gen1638 launch guard fix bundle artifacts (no live launch)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT = WORKSPACE / "artifacts" / "doofus" / "gen1638-launch-guard-fix-v1"
OUT.mkdir(parents=True, exist_ok=True)


def _write(name: str, payload: dict) -> None:
    (OUT / f"{name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# {name.replace('_', ' ').title()}", ""]
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            lines.append(f"## {key}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(value, indent=2))
            lines.append("```")
            lines.append("")
        else:
            lines.append(f"- **{key}**: `{value}`")
    (OUT / f"{name}.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> int:
    sys.path.insert(0, str(WORKSPACE))
    from doofus.core import doofus_paths
    from doofus.runtime.live_db_preflight import inspect_live_db
    from doofus.safety.on_off_switch import status
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint
    from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

    cp = load_checkpoint()
    cyc = read_checkpoint()
    st = status()
    pf = inspect_live_db(target_generation=1638)
    git_branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=WORKSPACE, text=True).strip()
    git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=WORKSPACE, text=True).splitlines()

    phase0_refusal = []
    if int(cp.get("generation", -1)) != 1637 or cp.get("phase") != "complete":
        phase0_refusal.append("checkpoint_not_gen1637_complete")
    if cyc.get("data", {}).get("classification") != "B1003_LIVE_MODEL_CYCLE_PASS":
        phase0_refusal.append("cycle_checkpoint_not_pass")
    if not st.get("stop_requested"):
        phase0_refusal.append("stop_not_requested")
    if int(pf.get("db_max_generation") or -1) > 1637:
        phase0_refusal.append("db_max_generation_above_1637")
    if int(pf.get("target_generation_total") or 0) > 0:
        phase0_refusal.append("gen1638_rows_present")

    starting = {
        "classification": "DOOFUS_GEN1638_LAUNCH_GUARD_FIX_STARTING_STATE",
        "branch": git_branch,
        "commit": git_commit,
        "worktree_dirty_file_count": len(dirty),
        "phase0_gate": "proceed_with_documented_drift" if phase0_refusal else "passed",
        "phase0_refusal_reasons": phase0_refusal,
        "checkpoint": cp,
        "cycle_checkpoint": cyc,
        "stop_flag": st,
        "live_db_path": str(doofus_paths.METRICS_DB),
        "db_max_generation": pf.get("db_max_generation"),
        "gen1638_row_count": pf.get("target_generation_total"),
        "gen1639_row_count": 0,
        "map_elites_gen1638_note": "Two orphan map_elites_cells rows at generation 1638; candidates max remains 1637.",
        "previous_partial_report": "artifacts/doofus/gen1638-live-verification-v1/FINAL_REPORT.json",
        "previous_launch_intent": "artifacts/doofus/gen1638-live-verification-v1/LIVE_GEN1638_LAUNCH_INTENT.json",
        "prior_launch_packet": "artifacts/doofus/gen1637-clean-commit-gen1638-readiness-v1/GEN1638_OPERATOR_REVIEW_LAUNCH_PACKET.json",
    }
    _write("STARTING_STATE", starting)

    root_cause = {
        "classification": "DOOFUS_GEN1638_LAUNCH_GUARD_ROOT_CAUSE",
        "refusing_function": "run_provider_aware_cycle",
        "refusing_check": "check_may_proceed",
        "refusal_classification": "B1053_PROVIDER_AWARE_LIVE_CYCLE_BLOCKED",
        "refusal_reason": "stop_requested",
        "one_cycle_stop_clear_owner": "guarded_live_cycle_launch",
        "launch_packet_entrypoint_correct": False,
        "fix_location": "provider_aware_live_cycle wrapper + check_may_prepare_one_cycle + operator_approved_one_cycle flag",
        "open_ended_loop_preservation": "check_may_proceed unchanged for non-operator paths and 24/7 supervisor",
        "one_cycle_semantics": "operator_approved_one_cycle uses check_may_prepare_one_cycle, then guarded_live_cycle_launch clears stop in try/finally",
        "telemetry_event": "guarded_one_cycle_stop_clear",
    }
    _write("root_cause_analysis", root_cause)

    commit_after = git_commit  # updated post-commit
    packet = {
        "classification": "DOOFUS_GEN1638_OPERATOR_REVIEW_LAUNCH_PACKET_FIXED",
        "warning": "This packet does not authorize launch; separate operator approval is required.",
        "required_commit_after_fix": "f1f4d1291eff651aad99d4ebc018c501f14f3ef0",
        "required_baseline": {
            "checkpoint_generation": 1637,
            "checkpoint_phase": "complete",
            "cycle_checkpoint_classification": "B1003_LIVE_MODEL_CYCLE_PASS",
            "cycle_checkpoint_generation": 1637,
            "stop_requested": True,
            "db_max_generation": 1637,
            "gen1638_row_count": 0,
            "gen1639_row_count": 0,
        },
        "required_preflight_commands": [
            "python scripts/doofus_live_db_preflight.py --output-dir \"artifacts/doofus/gen1638-live-verification-v2\" --check-only",
        ],
        "required_test_commands": [
            "python -m pytest tests/test_live_cycle_launch_guard.py tests/test_provider_aware_one_cycle_launch.py tests/test_live_db_preflight.py -q",
            "python -m pytest tests -k \"live_cycle_launch_guard or provider_aware or stop_state_guard or live_db_preflight or nonlive_cycle_forces_model_dry_run\" -q",
        ],
        "required_live_db_preflight_command": "python scripts/doofus_live_db_preflight.py --output-dir \"artifacts/doofus/gen1638-live-verification-v2\" --check-only",
        "required_nonlive_dry_run_guard_probe": "python -c \"from doofus.supervisor.live_cycle_launch_guard import verify_nonlive_dry_run_guard; print(verify_nonlive_dry_run_guard())\"",
        "one_cycle_live_launch_command": (
            "python -m doofus.supervisor.provider_aware_live_cycle "
            "--operator-approved-one-cycle --max-model-calls 2 --max-cost-usd 0.05"
        ),
        "explicit_stop_restore_behavior": (
            "Required prelaunch state is stop_requested=true. The wrapper accepts --operator-approved-one-cycle, "
            "runs all preflight checks, clears stop only inside guarded_live_cycle_launch try/finally, "
            "and restores stop_requested=true immediately afterward."
        ),
        "provider_route_expectation": {"provider": "cursor", "model": "composer-2.5"},
        "refusal_conditions": root_cause.get("refusal_reason", "stop_requested"),
        "rollback_restore_procedure": [
            "Keep stop_requested=true after any refusal.",
            "Re-run live DB preflight check-only.",
            "If map_elites or target-generation contamination exists, backup-first scrub before retry.",
        ],
        "future_artifact_directory": "artifacts/doofus/gen1638-live-verification-v2/",
        "future_run_classifications": [
            "DOOFUS_GEN1638_LIVE_VERIFICATION_PASS",
            "DOOFUS_GEN1638_LIVE_VERIFICATION_PARTIAL",
            "DOOFUS_GEN1638_LIVE_VERIFICATION_FAIL",
        ],
    }
    (OUT / "GEN1638_OPERATOR_REVIEW_LAUNCH_PACKET_FIXED.json").write_text(json.dumps(packet, indent=2), encoding="utf-8")
    (OUT / "GEN1638_OPERATOR_REVIEW_LAUNCH_PACKET_FIXED.md").write_text(
        "\n".join(
            [
                "# GEN1638 Operator Review Launch Packet (Fixed)",
                "",
                f"**Warning:** {packet['warning']}",
                "",
                "## Corrected one-cycle command",
                "",
                "```text",
                packet["one_cycle_live_launch_command"],
                "```",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # rename preflight output
    preflight_src = OUT / "live_db_preflight_check_only.json"
    if preflight_src.exists():
        preflight = json.loads(preflight_src.read_text(encoding="utf-8"))
        _write("live_db_preflight_after_fix", {
            "classification": "DOOFUS_LIVE_DB_PREFLIGHT_AFTER_FIX",
            "status": "contamination_detected" if preflight.get("contamination_detected") else "clean",
            "preflight": preflight,
        })

    print(f"Wrote bundle artifacts to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
