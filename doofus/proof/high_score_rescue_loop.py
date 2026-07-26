"""Inline high-score rescue — mine, enqueue, proof-build, shadow upgrade within cycle budget."""
from __future__ import annotations

import inspect
import time

from doofus.config.proof_builder_runtime_config import (
    high_score_rescue_mode,
    proof_builder_mode,
    inline_rescue_max_per_cycle,
    inline_rescue_max_seconds,
)
from doofus.proof.high_score_rejection_miner import MINER_DEADLINE_EXCEEDED, MINER_DEFERRED_DEADLINE
from doofus.core.atomic_json import append_jsonl
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import STATE
from doofus.proof.proof_candidate_selector import select_and_enqueue
from doofus.proof.proof_builder_runner import run_proof_builder_batch
from doofus.proof.proof_builder_queue import queue_summary
from doofus.evolution.shadow_elite_retester import retest_shadow_elites
from doofus.evolution.shadow_elite_upgrade_queue import process_upgrade_batch
from doofus.evolution.elite_archive_maintainer import maintain_elite_archive
from doofus.proof.inline_rescue_budget import (
    INLINE_RESCUE_SHADOW_UPGRADE_DEFERRED,
    SHADOW_UPGRADE_DEFERRED_DEADLINE,
    SHADOW_UPGRADE_PARTIAL,
    inline_rescue_init_max_seconds,
    policy_snapshot,
    shadow_upgrade_sub_deadline,
    should_defer_shadow_upgrade,
)

INLINE_RESCUE_EVENTS = STATE / "inline_rescue_events.jsonl"


def _record_inline_rescue_event(
    *,
    generation: int,
    event_type: str,
    stage: str,
    status: str,
    elapsed_seconds: float,
    timeout_threshold_ms: float,
    rescue_item_count: int,
    command_count: int,
    db_write_count: int,
    max_item_duration_ms: float,
    slowest_item_id: str,
    slowest_item_type: str,
    detail: dict | None = None,
) -> None:
    append_jsonl(
        INLINE_RESCUE_EVENTS,
        {
            "timestamp_utc": utc_now(),
            "generation": generation,
            "event_type": event_type,
            "stage": stage,
            "status": status,
            "elapsed_seconds": round(elapsed_seconds, 2),
            "timeout_threshold_ms": round(timeout_threshold_ms, 2),
            "rescue_item_count": int(rescue_item_count),
            "command_count": int(command_count),
            "db_write_count": int(db_write_count),
            "max_item_duration_ms": round(max_item_duration_ms, 2),
            "slowest_item_id": slowest_item_id,
            "slowest_item_type": slowest_item_type,
            "detail": detail or {},
        },
    )


def run_inline_rescue(
    *,
    baseline: float,
    generation: int,
    max_seconds: int | None = None,
    progress_callback=None,
    init_phase: bool = False,
) -> dict:
    max_seconds = int(max_seconds if max_seconds is not None else inline_rescue_max_seconds())
    if init_phase:
        max_seconds = min(max_seconds, int(inline_rescue_init_max_seconds()))
    start = time.monotonic()
    deadline = start + max_seconds
    timeout_threshold_ms = max_seconds * 1000.0
    command_count = 0
    rescue_item_count = 0
    db_write_count = 0
    max_item_duration_ms = 0.0
    slowest_item_id = ""
    slowest_item_type = ""

    def elapsed_seconds() -> float:
        return time.monotonic() - start

    def note_stage(stage: str, detail: dict, *, status: str = "ok", event_type: str = "progress") -> None:
        _record_inline_rescue_event(
            generation=generation,
            event_type=event_type,
            stage=stage,
            status=status,
            elapsed_seconds=elapsed_seconds(),
            timeout_threshold_ms=timeout_threshold_ms,
            rescue_item_count=rescue_item_count,
            command_count=command_count,
            db_write_count=db_write_count,
            max_item_duration_ms=max_item_duration_ms,
            slowest_item_id=slowest_item_id,
            slowest_item_type=slowest_item_type,
            detail=detail,
        )

    def report(stage: str, detail: dict) -> None:
        if progress_callback:
            progress_callback(stage, detail)
        note_stage(stage, detail)

    def update_batch_metrics(batch: dict) -> None:
        nonlocal command_count, rescue_item_count, db_write_count, max_item_duration_ms, slowest_item_id, slowest_item_type
        processed = int(batch.get("processed") or 0)
        command_count += int(batch.get("command_count") or processed)
        rescue_item_count += processed
        db_write_count += int(batch.get("db_write_count") or 0)
        candidate_duration = float(batch.get("max_item_duration_ms") or 0.0)
        if candidate_duration >= max_item_duration_ms:
            max_item_duration_ms = candidate_duration
            slowest_item_id = str(batch.get("slowest_item_id") or "")
            slowest_item_type = str(batch.get("slowest_item_type") or "")

    def timeout_result(stage: str, detail: dict) -> dict:
        note_stage(stage, detail, status="timeout", event_type="timeout")
        return {
            "active": True,
            "classification": "INLINE_RESCUE_TIMEOUT",
            "generation": generation,
            "timed_out": True,
            "timed_out_stage": stage,
            "elapsed_seconds": round(elapsed_seconds(), 2),
            "timeout_threshold_ms": timeout_threshold_ms,
            "queue": queue_summary(),
            "command_count": command_count,
            "rescue_item_count": rescue_item_count,
            "db_write_count": db_write_count,
            "max_item_duration_ms": round(max_item_duration_ms, 2),
            "slowest_item_id": slowest_item_id,
            "slowest_item_type": slowest_item_type,
            **detail,
        }

    def timed_out() -> bool:
        return time.monotonic() >= deadline

    if not proof_builder_mode() and not high_score_rescue_mode():
        note_stage("inline_rescue", {"reason": "modes_disabled"}, status="skipped", event_type="skip")
        return {"active": False, "classification": "INLINE_RESCUE_SKIPPED", "reason": "modes_disabled"}
    note_stage(
        "inline_rescue",
        {"baseline": baseline, "max_seconds": max_seconds, "init_phase": init_phase, "budget_policy": policy_snapshot()},
        status="started",
        event_type="start",
    )
    mined = {"enqueued": 0, "skipped": 0}
    HIGH_SCORE_MIN_BUDGET_SECONDS = 5.0
    if high_score_rescue_mode() and generation % 5 == 0:
        remaining = deadline - time.monotonic()
        if timed_out() or remaining < HIGH_SCORE_MIN_BUDGET_SECONDS:
            defer_detail = {
                "mined": mined,
                "reason": "insufficient_budget",
                "remaining_seconds": round(max(0.0, remaining), 2),
                "classification": MINER_DEFERRED_DEADLINE,
            }
            note_stage(
                "high_score_enqueue",
                defer_detail,
                status="skipped",
                event_type="high_score_enqueue_skipped_deadline",
            )
            note_stage(
                "inline_rescue_high_score_deferred",
                defer_detail,
                status="deferred",
                event_type="inline_rescue_high_score_deferred",
            )
        else:
            enqueue_kwargs = {"limit": 20, "generation": generation}
            if "deadline_monotonic" in inspect.signature(select_and_enqueue).parameters:
                enqueue_kwargs["deadline_monotonic"] = deadline
            mined = select_and_enqueue(**enqueue_kwargs)
            report("high_score_enqueue", mined)
            if mined.get("classification") in {MINER_DEFERRED_DEADLINE, MINER_DEADLINE_EXCEEDED}:
                note_stage(
                    "inline_rescue_high_score_deferred",
                    {"mined": mined, "classification": mined.get("classification")},
                    status="deferred",
                    event_type="inline_rescue_high_score_deferred",
                )
            elif mined.get("timed_out"):
                note_stage(
                    "high_score_enqueue_skipped_deadline",
                    {"mined": mined},
                    status="timeout",
                    event_type="high_score_enqueue_skipped_deadline",
                )
                return timeout_result("high_score_enqueue", {"mined": mined})
    if timed_out():
        return timeout_result("shadow_retest", {})
    retest = retest_shadow_elites(limit=10)
    report("shadow_retest", retest)
    if timed_out():
        return timeout_result("shadow_retest", {"shadow_retest": retest})
    shadow_limit = 5
    shadow_sub_deadline = shadow_upgrade_sub_deadline(deadline, init_phase=init_phase)
    defer_shadow, defer_shadow_reason = should_defer_shadow_upgrade(shadow_sub_deadline, init_phase=init_phase)
    report(
        "shadow_upgrade_start",
        {
            "limit": shadow_limit,
            "init_phase": init_phase,
            "defer_precheck": defer_shadow,
            "defer_reason": defer_shadow_reason,
            "remaining_seconds": round(max(0.0, (shadow_sub_deadline or deadline) - time.monotonic()), 2),
        },
    )
    if defer_shadow:
        upgrade = {
            "processed": 0,
            "deferred": True,
            "classification": SHADOW_UPGRADE_DEFERRED_DEADLINE,
            "defer_reason": defer_shadow_reason,
        }
        note_stage(
            "inline_rescue_shadow_upgrade_deferred",
            {"shadow_upgrade": upgrade, "classification": INLINE_RESCUE_SHADOW_UPGRADE_DEFERRED},
            status="deferred",
            event_type="inline_rescue_shadow_upgrade_deferred",
        )
        report("shadow_upgrade_deferred", upgrade)
    else:
        upgrade = process_upgrade_batch(
            limit=shadow_limit,
            baseline=baseline,
            progress_callback=report,
            deadline_monotonic=shadow_sub_deadline,
            init_phase=init_phase,
            generation=generation,
        )
        update_batch_metrics(upgrade)
        report("shadow_upgrade", upgrade)
        if upgrade.get("classification") in {SHADOW_UPGRADE_DEFERRED_DEADLINE, SHADOW_UPGRADE_PARTIAL}:
            note_stage(
                "inline_rescue_shadow_upgrade_deferred",
                {"shadow_upgrade": upgrade, "classification": INLINE_RESCUE_SHADOW_UPGRADE_DEFERRED},
                status="deferred",
                event_type="inline_rescue_shadow_upgrade_deferred",
            )
        elif upgrade.get("deferred"):
            note_stage(
                "inline_rescue_shadow_upgrade_deferred",
                {"shadow_upgrade": upgrade, "classification": INLINE_RESCUE_SHADOW_UPGRADE_DEFERRED},
                status="deferred",
                event_type="inline_rescue_shadow_upgrade_deferred",
            )
    if timed_out() and upgrade.get("classification") not in {SHADOW_UPGRADE_DEFERRED_DEADLINE} and not upgrade.get("deferred"):
        return timeout_result("shadow_upgrade", {"shadow_upgrade": upgrade})
    if timed_out():
        return timeout_result("elite_archive", {})
    maint_kwargs: dict = {}
    if "deadline_monotonic" in inspect.signature(maintain_elite_archive).parameters:
        maint_kwargs["deadline_monotonic"] = deadline
    elite_maint = maintain_elite_archive(**maint_kwargs)
    report("elite_archive", elite_maint)
    if elite_maint.get("timed_out") or timed_out():
        return timeout_result("elite_archive", {"elite_archive": elite_maint})
    if timed_out():
        return timeout_result("elite_archive", {"elite_archive": elite_maint})
    remaining = max(0.0, max_seconds - (time.monotonic() - start))
    batch = {"processed": 0, "successes": 0, "failures": 0}
    if proof_builder_mode() and remaining > 1.0:
        limit = inline_rescue_max_per_cycle()
        report("proof_builder_start", {"limit": limit, "remaining_seconds": round(remaining, 2)})
        batch = run_proof_builder_batch(limit=limit, baseline=baseline, progress_callback=report, deadline_monotonic=deadline)
        update_batch_metrics(batch)
        report("proof_builder_complete", {"processed": batch.get("processed", 0), "successes": batch.get("successes", 0), "failures": batch.get("failures", 0)})
    elif proof_builder_mode():
        note_stage("proof_builder_start", {"remaining_seconds": round(remaining, 2)}, status="skipped", event_type="skip")
    result = {
        "active": True,
        "classification": "INLINE_RESCUE_OK",
        "generation": generation,
        "timed_out": False,
        "mined": mined,
        "shadow_retest": retest,
        "shadow_upgrade": upgrade,
        "elite_archive": elite_maint,
        "proof_builder_batch": batch,
        "queue": queue_summary(),
        "elapsed_seconds": round(time.monotonic() - start, 2),
        "timeout_threshold_ms": timeout_threshold_ms,
        "command_count": command_count,
        "rescue_item_count": rescue_item_count,
        "db_write_count": db_write_count,
        "max_item_duration_ms": round(max_item_duration_ms, 2),
        "slowest_item_id": slowest_item_id,
        "slowest_item_type": slowest_item_type,
    }
    note_stage(
        "inline_rescue",
        {
            "classification": result["classification"],
            "queue_size": result["queue"].get("queue_size"),
            "processed": rescue_item_count,
        },
        status="ok",
        event_type="end",
    )
    return result
