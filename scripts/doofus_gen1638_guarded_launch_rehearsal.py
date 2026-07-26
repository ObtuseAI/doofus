"""Simulated guarded one-cycle launch rehearsal - no live provider, no canonical DB."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))


def _require_temp_runtime() -> None:
    if os.environ.get("DOOFUS_ALLOW_LIVE_RUNTIME_TESTS", "0") == "1":
        raise SystemExit("refusing rehearsal with DOOFUS_ALLOW_LIVE_RUNTIME_TESTS=1")
    required = ("DOOFUS_ROOT", "DOOFUS_RUNTIME", "DOOFUS_STATE", "DOOFUS_METRICS_DB")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"refusing rehearsal without isolated runtime overrides: {missing}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Guarded gen1638 launch rehearsal (stubbed only).")
    parser.add_argument(
        "--output-dir",
        default=str(WORKSPACE / "artifacts" / "doofus" / "gen1638-launch-guard-fix-v1"),
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _require_temp_runtime()

    import json as json_mod

    from doofus.core import doofus_paths
    from doofus.safety.on_off_switch import status as switch_status
    from doofus.supervisor import live_cycle_launch_guard as guard
    from doofus.supervisor.doofus_crash_recovery import load_checkpoint

    from doofus.supervisor import doofus_crash_recovery as crash_recovery
    from doofus.supervisor import doofus_cycle_checkpoint as cycle_checkpoint_mod
    from doofus.core.doofus_state import init_db

    init_db()
    doofus_paths.RUN_ENABLED.parent.mkdir(parents=True, exist_ok=True)
    doofus_paths.RUN_ENABLED.write_text("enabled", encoding="utf-8")
    doofus_paths.STOP_REQUEST.write_text("stop", encoding="utf-8")
    crash_recovery.CHECKPOINT.write_text(
        json_mod.dumps(
            {
                "generation": 1637,
                "baseline_score": 0.9378,
                "run_id": "rehearsal-run",
                "phase": "complete",
                "saved_at": "2026-07-04T00:00:00+00:00",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    cycle_checkpoint_mod.CHECKPOINT.write_text(
        json_mod.dumps(
            {
                "stage": "cycle_complete",
                "data": {"classification": "B1003_LIVE_MODEL_CYCLE_PASS", "generation": 1637},
                "saved_at": "2026-07-04T00:00:01+00:00",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    stop_before = switch_status()
    checkpoint_before = load_checkpoint()
    stub_invocations = {"count": 0}

    def _stub_cycle(**_kwargs) -> dict:
        stub_invocations["count"] += 1
        return {
            "classification": "DOOFUS_CYCLE_COMPLETE",
            "model_result": {"classification": "DOOFUS_MODEL_REHEARSAL_STUB"},
            "generation": 1638,
        }

    guard.EVENTS = output_dir / "rehearsal_live_cycle_launch_guard_events.jsonl"
    guard.GUARDED_STOP_CLEAR_EVENTS = output_dir / "rehearsal_guarded_one_cycle_stop_clear_events.jsonl"
    guard.ONE_CYCLE_ACTIVE_MARKER = output_dir / "rehearsal_one_cycle_launch_active.marker"

    result = guard.guarded_live_cycle_launch(
        requested_live_mode=True,
        one_cycle_only=True,
        operator_approved_one_cycle=True,
        requested_target_generation=1638,
        run_cycle=_stub_cycle,
    )
    stop_after = switch_status()
    checkpoint_after = load_checkpoint()

    report = {
        "classification": "DOOFUS_GEN1638_GUARDED_LAUNCH_REHEARSAL",
        "mode": "simulated_stubbed_only",
        "stop_before": stop_before,
        "stop_after": stop_after,
        "checkpoint_before": checkpoint_before,
        "checkpoint_after": checkpoint_after,
        "target_generation": 1638,
        "launch_result": result,
        "live_provider_route_invoked": False,
        "stub_cycle_invocations": stub_invocations["count"],
        "guarded_path_reached_cycle": stub_invocations["count"] > 0,
        "metrics_db_path": str(doofus_paths.METRICS_DB),
        "stop_restored": bool(stop_after.get("stop_requested")),
        "checkpoint_unchanged": checkpoint_before == checkpoint_after,
    }

    json_path = output_dir / "guarded_launch_rehearsal.json"
    md_path = output_dir / "guarded_launch_rehearsal.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_lines = [
        "# Guarded Launch Rehearsal",
        "",
        f"- classification: `{report['classification']}`",
        f"- mode: `{report['mode']}`",
        f"- stop_restored: `{report['stop_restored']}`",
        f"- checkpoint_unchanged: `{report['checkpoint_unchanged']}`",
        f"- stub_cycle_invocations: `{report['stub_cycle_invocations']}`",
        f"- launch_decision: `{result.get('decision')}`",
    ]
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(json_path)
    print(md_path)
    ok = report["stop_restored"] and report["checkpoint_unchanged"] and report["guarded_path_reached_cycle"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
