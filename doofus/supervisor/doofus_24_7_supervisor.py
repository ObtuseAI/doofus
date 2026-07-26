"""24/7 supervisor loop — single instance, obeys switch without exiting on emergency."""

from __future__ import annotations

import argparse
import os

import time

from doofus.core.doofus_config import DoofusConfig

from doofus.config.proof_builder_runtime_config import bootstrap_autonomous_runtime, runtime_snapshot as proof_runtime

from doofus.config.evolution_runtime_config import runtime_snapshot as evo_runtime

from doofus.evolution.adaptive_mutation_pressure import get_pressure_state

from doofus.safety.budget_guard import check_budget

from doofus.safety.on_off_switch import check_may_proceed, status

from doofus.meta.recursive_supervisor import run_meta_cycle

from doofus.supervisor.doofus_heartbeat import emit_heartbeat

from doofus.supervisor.process_singleton import acquire_singleton, release_singleton





def _sleep_with_heartbeat(total_seconds: float) -> None:

    """Sleep in chunks while emitting heartbeat so stale detection stays accurate."""

    remaining = float(total_seconds)

    while remaining > 0:

        chunk = min(30.0, remaining)

        time.sleep(chunk)

        remaining -= chunk

        emit_heartbeat("supervisor_alive", {"sleep_remaining": round(remaining, 1)})





def _cycle_sleep_seconds(cfg: DoofusConfig) -> float:

    """Accelerate cycles during stagnation when budget allows."""

    ps = get_pressure_state()

    stagnation = int(ps.get("stagnation_cycles", 0))
    budget = check_budget(cfg)
    fast_at = int(os.environ.get("DOOFUS_SUPERVISOR_STAGNATION_FAST_SLEEP_AT", "5"))
    if stagnation >= fast_at and budget.get("ok"):
        return float(cfg.min_cycle_sleep_seconds)

    return float(cfg.cycle_sleep_seconds)


def _counts_as_completed_attempt(classification: str | None) -> bool:
    return classification in {
        "DOOFUS_CYCLE_COMPLETE",
        "B1003_LIVE_MODEL_CYCLE_PASS",
        "B1003_LIVE_MODEL_CYCLE_DRY_RUN_FALLBACK",
        "B1003_LIVE_MODEL_CYCLE_PASS_WITH_NOTES",
        "DOOFUS_CYCLE_TIMEOUT",
        "DOOFUS_CYCLE_FAILED",
        "DOOFUS_CYCLE_INTERRUPTED",
    }





def run_supervisor(*, max_cycles: int | None = None) -> int:

    bootstrap_autonomous_runtime()

    if not acquire_singleton("doofus_supervisor"):

        emit_heartbeat("supervisor_duplicate_blocked", {"pid": "existing"})

        return 0

    cfg = DoofusConfig.from_env()

    cycles = 0

    emit_heartbeat("supervisor_start", {**status(), "autonomous_runtime": proof_runtime(), "evolution_runtime": evo_runtime()})

    try:

        while True:

            may, reason = check_may_proceed()

            if not may:

                emit_heartbeat("supervisor_idle", {"reason": reason, **status()})

                _sleep_with_heartbeat(cfg.min_cycle_sleep_seconds)

                continue

            try:
                inner = run_meta_cycle(dry_run=False, live_model_if_available=True)
                classification = inner.get("classification")
                if _counts_as_completed_attempt(classification):
                    cycles += 1
                if classification in {
                    "DOOFUS_CYCLE_TIMEOUT",
                    "DOOFUS_CYCLE_FAILED",
                    "DOOFUS_CYCLE_INTERRUPTED",
                }:
                    emit_heartbeat("supervisor_cycle_terminal", {"classification": classification})
                    break
            except Exception as exc:
                from doofus.core.pipeline_log import pipeline_warn
                pipeline_warn("supervisor", f"cycle error: {type(exc).__name__}", exc=exc)
                emit_heartbeat("supervisor_cycle_error", {"error": type(exc).__name__})
                _sleep_with_heartbeat(min(cfg.min_cycle_sleep_seconds, 30.0))
                continue

            if max_cycles and cycles >= max_cycles:

                break

            sleep_s = max(cfg.min_cycle_sleep_seconds, _cycle_sleep_seconds(cfg))

            _sleep_with_heartbeat(sleep_s)

    finally:

        release_singleton("doofus_supervisor")

    return 0





def main() -> int:

    p = argparse.ArgumentParser()

    p.add_argument("--max-cycles", type=int, default=None)

    args = p.parse_args()

    return run_supervisor(max_cycles=args.max_cycles)





if __name__ == "__main__":

    raise SystemExit(main())
