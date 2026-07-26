"""CLI for autonomous live runner."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from doofus.core.doofus_env_loader import load_doofus_env

load_doofus_env()

from doofus.reports.cycle_finalizer import write_artifact_pair
from doofus.supervisor.autonomous_live_runner import AutonomousLiveRunner, RunnerConfig


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--stop-dry-run", action="store_true", help="Verify stop path without mutating stop flag")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--max-runtime-minutes", type=int, default=30)
    parser.add_argument("--max-cost-usd", type=float, default=0.05)
    parser.add_argument("--sleep-seconds", type=int, default=60)
    parser.add_argument("--provider", default="openrouter")
    parser.add_argument("--model-alias", default="deepseekv4flash")
    parser.add_argument("--operator-approved-autonomous-live", action="store_true")
    parser.add_argument("--require-postlive-certification", action="store_true", default=True)
    parser.add_argument("--proof-builder-first", action="store_true")
    parser.add_argument("--no-live-if-proof-queue-pending", action="store_true")
    parser.add_argument("--output-dir", default=str(WORKSPACE / "artifacts" / "doofus" / "openrouter-deepseek-autonomous-live-v1"))
    args = parser.parse_args()

    cfg = RunnerConfig(
        dry_run=args.dry_run or not args.operator_approved_autonomous_live,
        once=args.once or not args.daemon,
        daemon=args.daemon,
        operator_approved=args.operator_approved_autonomous_live,
        provider=args.provider,
        model_alias=args.model_alias,
        max_cycles=args.max_cycles,
        max_runtime_minutes=args.max_runtime_minutes,
        max_cost_usd=args.max_cost_usd,
        sleep_seconds=args.sleep_seconds,
        require_postlive_certification=args.require_postlive_certification,
        proof_builder_first=args.proof_builder_first,
        no_live_if_proof_queue_pending=args.no_live_if_proof_queue_pending,
        output_dir=Path(args.output_dir),
    )
    runner = AutonomousLiveRunner(cfg)

    if args.status:
        payload = runner.status()
        print(json.dumps(payload, indent=2))
        return 0

    if args.stop_dry_run:
        from doofus.safety.on_off_switch import status

        payload = {
            "classification": "DOOFUS_AUTONOMOUS_LIVE_RUNNER_STOP_DRY_RUN",
            "would_invoke": "doofus.safety.on_off_switch.stop",
            "stop_flag_before": status(),
            "state_mutated": False,
        }
        write_artifact_pair(Path(args.output_dir), "AUTONOMOUS_RUNNER_STOP_DRY_RUN", payload)
        print(json.dumps(payload, indent=2))
        return 0

    if args.stop:
        from doofus.safety.on_off_switch import stop
        from doofus.supervisor.autonomous_run_lease import request_external_halt

        stop()
        request_external_halt(reason="operator_stop_cli")
        payload = {"classification": "DOOFUS_AUTONOMOUS_LIVE_RUNNER_HALTED_BY_STOP", "action": "stop_requested"}
        write_artifact_pair(Path(args.output_dir), "AUTONOMOUS_RUNNER_STOP", payload)
        print(json.dumps(payload, indent=2))
        return 0

    payload = runner.run()
    stem = "AUTONOMOUS_RUNNER_DRY_RUN_RESULT" if cfg.dry_run else "AUTONOMOUS_LIVE_START_RESULT"
    write_artifact_pair(Path(args.output_dir), stem, payload)
    print(json.dumps({"classification": payload["classification"]}, indent=2))
    return 0 if "PASS" in payload["classification"] or payload["classification"].endswith("STARTED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
