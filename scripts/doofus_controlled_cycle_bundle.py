"""Thin CLI entry for reusable controlled-cycle modes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.reports.cycle_certification import build_prep_only_launch_packet
from doofus.reports.cycle_finalizer import write_artifact_pair
from doofus.reports.cycle_orchestrator import (
    run_inline_rescue_rehearsal,
    run_live_db_preflight,
    run_live_one_cycle,
    run_miner_readiness,
    run_nonlive_dry_run_probe,
    run_shadow_readiness,
    validate_controlled_cycle_policy,
)
from doofus.supervisor.controlled_cycle import ControlledCycleMode, requires_operator_approval


def main() -> int:
    parser = argparse.ArgumentParser(description="Doofus controlled-cycle bundle helper")
    parser.add_argument(
        "--mode",
        choices=[m.value for m in ControlledCycleMode],
        default=ControlledCycleMode.PREFLIGHT_ONLY.value,
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--source-generation", type=int, default=1642)
    parser.add_argument("--target-generation", type=int, default=1643)
    parser.add_argument("--certified-generation", type=int, default=None)
    parser.add_argument("--next-generation", type=int, default=None)
    parser.add_argument("--operator-approved-one-cycle", action="store_true")
    args = parser.parse_args()

    certified = args.certified_generation if args.certified_generation is not None else args.source_generation
    nxt = args.next_generation if args.next_generation is not None else args.target_generation
    mode = ControlledCycleMode(args.mode)
    out = Path(args.output_dir)

    if mode == ControlledCycleMode.LIVE_VERIFICATION and not args.operator_approved_one_cycle:
        payload = {
            "classification": "DOOFUS_CONTROLLED_CYCLE_REFUSED",
            "reason": "live_verification requires --operator-approved-one-cycle",
        }
        write_artifact_pair(out, "CONTROLLED_CYCLE_REFUSAL", payload)
        print(json.dumps(payload, indent=2))
        return 1

    if mode == ControlledCycleMode.PREFLIGHT_ONLY:
        pf = run_live_db_preflight(out)
        result = {
            "classification": "DOOFUS_CONTROLLED_CYCLE_PREFLIGHT",
            "mode": mode.value,
            "live_route_invoked": False,
            **pf,
        }
        write_artifact_pair(out, "CONTROLLED_CYCLE_MODE_RESULT", result)
        print(json.dumps(result, indent=2))
        return 0 if pf.get("passed") else 1

    if mode in (ControlledCycleMode.PREP_ONLY, ControlledCycleMode.POSTLIVE_CERTIFICATION):
        packet = build_prep_only_launch_packet(next_generation=nxt, certified_generation=certified)
        write_artifact_pair(out, f"GEN{nxt}_OPERATOR_REVIEW_LAUNCH_PACKET_PREP_ONLY", packet)
        result = {
            "classification": "DOOFUS_CONTROLLED_CYCLE_POSTLIVE_PREP",
            "mode": mode.value,
            "prep_packet_written": True,
            "live_route_invoked": False,
            "requires_operator_approval_for_next_live": True,
        }
        if mode == ControlledCycleMode.POSTLIVE_CERTIFICATION:
            policy_path = WORKSPACE / "artifacts" / "doofus" / "gen1641-postlive-certification-loop-hardening-v1" / "CONTROLLED_CYCLE_LOOP_POLICY.json"
            if not policy_path.exists():
                policy_path = WORKSPACE / "artifacts" / "doofus" / "full-completion-master-v1" / "CONTROLLED_CYCLE_LOOP_POLICY.json"
            result["policy_validation"] = validate_controlled_cycle_policy(policy_path)
            result["preflight"] = run_live_db_preflight(out)
            result["nonlive_probe"] = run_nonlive_dry_run_probe()
        write_artifact_pair(out, "CONTROLLED_CYCLE_MODE_RESULT", result)
        print(json.dumps(result, indent=2))
        return 0

    if mode == ControlledCycleMode.REPAIR_READINESS:
        miner = run_miner_readiness(nxt, out, stem="REPAIR_MINER_READINESS")
        shadow = run_shadow_readiness(nxt, out, stem="REPAIR_SHADOW_READINESS")
        nonlive = run_nonlive_dry_run_probe()
        passed = miner.get("passed") and shadow.get("passed") and nonlive.get("passed")
        result = {
            "classification": "DOOFUS_CONTROLLED_CYCLE_REPAIR_READINESS",
            "mode": mode.value,
            "passed": passed,
            "miner": miner,
            "shadow": shadow,
            "nonlive_probe": nonlive,
            "live_route_invoked": False,
        }
        write_artifact_pair(out, "CONTROLLED_CYCLE_MODE_RESULT", result)
        print(json.dumps(result, indent=2))
        return 0 if passed else 1

    if mode == ControlledCycleMode.LIVE_VERIFICATION:
        live = run_live_one_cycle(operator_approved=True)
        result = {
            "classification": "DOOFUS_CONTROLLED_CYCLE_LIVE_ONE_CYCLE",
            "mode": mode.value,
            "live_route_invoked": True,
            **live,
        }
        write_artifact_pair(out, "CONTROLLED_CYCLE_LIVE_RESULT", result)
        print(json.dumps({"classification": result["classification"], "exit_code": live.get("exit_code")}, indent=2))
        return 0 if live.get("exit_code") == 0 else 1

    result = {
        "classification": "DOOFUS_CONTROLLED_CYCLE_MODE",
        "mode": mode.value,
        "requires_operator_approval": requires_operator_approval(mode),
        "live_route_allowed": mode == ControlledCycleMode.LIVE_VERIFICATION and args.operator_approved_one_cycle,
        "live_route_invoked": False,
    }
    write_artifact_pair(out, "CONTROLLED_CYCLE_MODE_RESULT", result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
