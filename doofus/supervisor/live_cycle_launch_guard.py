"""Guarded single-cycle live launch helper."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from doofus.core import doofus_paths
from doofus.core.atomic_json import append_jsonl
from doofus.core.doofus_config import DoofusConfig
from doofus.core.doofus_events import utc_now
from doofus.model_router.provider_router import resolve_provider
from doofus.runtime.live_db_preflight import inspect_live_db
from doofus.safety.on_off_switch import (
    check_may_proceed,
    start as switch_start,
    status as switch_status,
    stop as switch_stop,
)
from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint

EVENTS = doofus_paths.STATE / "live_cycle_launch_guard_events.jsonl"
GUARDED_STOP_CLEAR_EVENTS = doofus_paths.STATE / "guarded_one_cycle_stop_clear_events.jsonl"
ONE_CYCLE_ACTIVE_MARKER = doofus_paths.STATE / "one_cycle_launch_active.marker"


def verify_nonlive_dry_run_guard() -> dict:
    previous = os.environ.get("DOOFUS_FORCE_MODEL_DRY_RUN")
    os.environ["DOOFUS_FORCE_MODEL_DRY_RUN"] = "1"
    try:
        cfg = DoofusConfig.from_env()
        route = resolve_provider()
        classification = "DOOFUS_MODEL_DRY_RUN" if cfg.model_mode == "dry_run" else "DOOFUS_MODEL_DRY_RUN_GUARD_FAILED"
        return {
            "classification": classification,
            "model_mode": cfg.model_mode,
            "provider_selected": route.get("provider_selected"),
        }
    finally:
        if previous is None:
            os.environ.pop("DOOFUS_FORCE_MODEL_DRY_RUN", None)
        else:
            os.environ["DOOFUS_FORCE_MODEL_DRY_RUN"] = previous


def record_live_cycle_launch_guard_event(
    *,
    checkpoint_generation: int,
    checkpoint_phase: str,
    requested_target_generation: int,
    requested_live_mode: bool,
    one_cycle_only: bool,
    stop_state_before: dict,
    stop_state_restored: bool,
    db_target_generation_count_before: int,
    db_above_target_generation_count_before: int,
    nonlive_guard_classification: str,
    decision: str,
    refusal_reason: str = "",
) -> dict:
    row = {
        "timestamp": utc_now(),
        "checkpoint_generation": checkpoint_generation,
        "checkpoint_phase": checkpoint_phase,
        "requested_target_generation": requested_target_generation,
        "requested_live_mode": bool(requested_live_mode),
        "one_cycle_only": bool(one_cycle_only),
        "stop_state_before": stop_state_before,
        "stop_state_restored": bool(stop_state_restored),
        "db_target_generation_count_before": int(db_target_generation_count_before),
        "db_above_target_generation_count_before": int(db_above_target_generation_count_before),
        "nonlive_guard_classification": nonlive_guard_classification,
        "decision": decision,
        "refusal_reason": refusal_reason or None,
    }
    append_jsonl(EVENTS, row)
    return row


def record_guarded_one_cycle_stop_clear_event(
    *,
    target_generation: int,
    operator_approved_one_cycle: bool,
    stop_state_before: dict,
    preflight_passed: bool,
    stop_clear_entered: bool,
    stop_state_during: dict | None,
    lower_level_check_result: dict,
    stop_restore_attempted: bool,
    stop_state_after: dict,
    decision: str,
    refusal_reason: str = "",
    live_route_invoked: bool = False,
    checkpoint_before: dict | None = None,
    checkpoint_after: dict | None = None,
    db_max_generation_before: int = -1,
    db_max_generation_after: int = -1,
) -> dict:
    row = {
        "event": "guarded_one_cycle_stop_clear",
        "timestamp": utc_now(),
        "target_generation": int(target_generation),
        "operator_approved_one_cycle": bool(operator_approved_one_cycle),
        "stop_state_before": stop_state_before,
        "preflight_passed": bool(preflight_passed),
        "stop_clear_entered": bool(stop_clear_entered),
        "stop_state_during": stop_state_during,
        "lower_level_check_result": lower_level_check_result,
        "stop_restore_attempted": bool(stop_restore_attempted),
        "stop_state_after": stop_state_after,
        "decision": decision,
        "refusal_reason": refusal_reason or None,
        "live_route_invoked": bool(live_route_invoked),
        "checkpoint_before": checkpoint_before,
        "checkpoint_after": checkpoint_after,
        "db_max_generation_before": int(db_max_generation_before),
        "db_max_generation_after": int(db_max_generation_after),
    }
    append_jsonl(GUARDED_STOP_CLEAR_EVENTS, row)
    return row


def _set_one_cycle_active() -> None:
    ONE_CYCLE_ACTIVE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    ONE_CYCLE_ACTIVE_MARKER.write_text(f"active_at={utc_now()}\n", encoding="utf-8")


def _clear_one_cycle_active() -> None:
    ONE_CYCLE_ACTIVE_MARKER.unlink(missing_ok=True)


def _one_cycle_active() -> bool:
    return ONE_CYCLE_ACTIVE_MARKER.exists()


def guarded_live_cycle_launch(
    *,
    requested_live_mode: bool,
    one_cycle_only: bool,
    run_cycle: Callable[..., dict],
    requested_target_generation: int | None = None,
    operator_approved_one_cycle: bool = False,
) -> dict:
    checkpoint = load_checkpoint()
    cycle_checkpoint = read_checkpoint()
    checkpoint_generation = int(checkpoint.get("generation", -1))
    checkpoint_phase = str(checkpoint.get("phase") or "")
    target_generation = int(requested_target_generation or (checkpoint_generation + 1))
    stop_before = switch_status()
    nonlive_guard = verify_nonlive_dry_run_guard()
    preflight = inspect_live_db(
        checkpoint_generation=checkpoint_generation,
        target_generation=target_generation,
    )
    target_before = int(preflight.get("target_generation_total") or 0)
    above_before = int(preflight.get("above_target_generation_total") or 0)
    db_max_before = int(preflight.get("db_max_generation") or -1)

    refusal_reason = ""
    if requested_live_mode is not True:
        refusal_reason = "requested_live_mode_must_be_true"
    elif one_cycle_only is not True:
        refusal_reason = "one_cycle_only_required"
    elif operator_approved_one_cycle and not stop_before.get("stop_requested", False):
        refusal_reason = "stop_not_requested_for_one_cycle"
    elif operator_approved_one_cycle and _one_cycle_active():
        refusal_reason = "one_cycle_launch_already_active"
    elif checkpoint_phase != "complete":
        refusal_reason = "checkpoint_not_complete"
    elif int(cycle_checkpoint.get("data", {}).get("generation", -1)) != checkpoint_generation:
        refusal_reason = "cycle_checkpoint_generation_mismatch"
    elif preflight.get("checkpoint_state_ambiguous"):
        refusal_reason = "checkpoint_state_ambiguous"
    elif target_before > 0:
        refusal_reason = "target_generation_already_present"
    elif above_before > 0:
        refusal_reason = "rows_present_above_target_generation"
    elif nonlive_guard.get("classification") != "DOOFUS_MODEL_DRY_RUN":
        refusal_reason = "nonlive_dry_run_guard_failed"

    preflight_passed = not refusal_reason
    if refusal_reason:
        record_live_cycle_launch_guard_event(
            checkpoint_generation=checkpoint_generation,
            checkpoint_phase=checkpoint_phase,
            requested_target_generation=target_generation,
            requested_live_mode=requested_live_mode,
            one_cycle_only=one_cycle_only,
            stop_state_before=stop_before,
            stop_state_restored=stop_before.get("stop_requested", False),
            db_target_generation_count_before=target_before,
            db_above_target_generation_count_before=above_before,
            nonlive_guard_classification=nonlive_guard.get("classification", ""),
            decision="refused",
            refusal_reason=refusal_reason,
        )
        if operator_approved_one_cycle:
            record_guarded_one_cycle_stop_clear_event(
                target_generation=target_generation,
                operator_approved_one_cycle=operator_approved_one_cycle,
                stop_state_before=stop_before,
                preflight_passed=False,
                stop_clear_entered=False,
                stop_state_during=None,
                lower_level_check_result={"may_proceed": False, "reason": refusal_reason},
                stop_restore_attempted=False,
                stop_state_after=stop_before,
                decision="refused",
                refusal_reason=refusal_reason,
                live_route_invoked=False,
                checkpoint_before=checkpoint,
                checkpoint_after=checkpoint,
                db_max_generation_before=db_max_before,
                db_max_generation_after=db_max_before,
            )
        return {
            "classification": "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_REFUSED",
            "reason": refusal_reason,
            "preflight": preflight,
            "nonlive_guard": nonlive_guard,
        }

    stop_changed = operator_approved_one_cycle or not stop_before.get("may_run", False)
    stop_after_run = stop_before
    stop_clear_entered = False
    stop_state_during: dict | None = None
    lower_level_check_result: dict = {"may_proceed": True, "reason": "not_checked"}
    live_route_invoked = False
    decision = "refused"
    cycle_refusal_reason = ""
    try:
        _set_one_cycle_active()
        if stop_changed:
            stop_clear_entered = True
            stop_state_during = switch_start()
        may_proceed, proceed_reason = check_may_proceed()
        lower_level_check_result = {"may_proceed": may_proceed, "reason": proceed_reason}
        if not may_proceed:
            cycle_refusal_reason = proceed_reason
            return {
                "classification": "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_REFUSED",
                "reason": proceed_reason,
                "preflight": preflight,
                "nonlive_guard": nonlive_guard,
            }
        live_route_invoked = True
        result = run_cycle(dry_run=False, live_model_if_available=True)
        model_cls = str(result.get("model_result", {}).get("classification") or "")
        if model_cls in {"DOOFUS_MODEL_DRY_RUN", "DOOFUS_MODEL_GATE_BLOCKED"}:
            decision = "refused"
            cycle_refusal_reason = "live_cycle_did_not_remain_live"
        else:
            decision = "allowed"
            cycle_refusal_reason = ""
        return {
            "classification": "DOOFUS_LIVE_CYCLE_LAUNCH_GUARD_RESULT",
            "decision": decision,
            "refusal_reason": cycle_refusal_reason,
            "result": result,
            "preflight": preflight,
            "nonlive_guard": nonlive_guard,
        }
    finally:
        stop_restore_attempted = False
        if stop_changed:
            stop_restore_attempted = True
            stop_after_run = switch_stop()
        else:
            stop_after_run = switch_status()
        _clear_one_cycle_active()
        checkpoint_after = load_checkpoint()
        after_preflight = inspect_live_db(
            checkpoint_generation=checkpoint_generation,
            target_generation=target_generation,
        )
        record_live_cycle_launch_guard_event(
            checkpoint_generation=checkpoint_generation,
            checkpoint_phase=checkpoint_phase,
            requested_target_generation=target_generation,
            requested_live_mode=requested_live_mode,
            one_cycle_only=one_cycle_only,
            stop_state_before=stop_before,
            stop_state_restored=bool(stop_after_run.get("stop_requested", False)),
            db_target_generation_count_before=target_before,
            db_above_target_generation_count_before=above_before,
            nonlive_guard_classification=nonlive_guard.get("classification", ""),
            decision="allowed" if decision == "allowed" and not cycle_refusal_reason else "refused",
            refusal_reason=cycle_refusal_reason,
        )
        if operator_approved_one_cycle:
            record_guarded_one_cycle_stop_clear_event(
                target_generation=target_generation,
                operator_approved_one_cycle=operator_approved_one_cycle,
                stop_state_before=stop_before,
                preflight_passed=preflight_passed,
                stop_clear_entered=stop_clear_entered,
                stop_state_during=stop_state_during,
                lower_level_check_result=lower_level_check_result,
                stop_restore_attempted=stop_restore_attempted,
                stop_state_after=stop_after_run,
                decision=decision if not cycle_refusal_reason else "refused",
                refusal_reason=cycle_refusal_reason,
                live_route_invoked=live_route_invoked,
                checkpoint_before=checkpoint,
                checkpoint_after=checkpoint_after,
                db_max_generation_before=db_max_before,
                db_max_generation_after=int(after_preflight.get("db_max_generation") or db_max_before),
            )
