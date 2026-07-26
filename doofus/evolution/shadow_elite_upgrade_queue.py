"""Shadow elite upgrade queue — retest and promote when gates pass."""
from __future__ import annotations

import json
import time

from doofus.core.doofus_paths import METRICS_DB, STATE
from doofus.evolution.shadow_elite_archive import _load as load_shadow, increment_failed_attempts
from doofus.evolution.shadow_upgrade_telemetry import record_shadow_upgrade_event
from doofus.proof.inline_rescue_budget import (
    SHADOW_UPGRADE_DEFERRED_DEADLINE,
    SHADOW_UPGRADE_ITEM_TIMEOUT,
    SHADOW_UPGRADE_PARTIAL,
    effective_item_limit,
    effective_item_timeout_seconds,
    remaining_seconds,
    should_defer_shadow_upgrade,
    shadow_upgrade_sub_deadline,
)
from doofus.proof.proof_builder_queue import enqueue
from doofus.proof.proof_builder_runner import run_process_one_guarded

STATS = STATE / "shadow_elite_upgrade_stats.json"


def _load_stats() -> dict:
    if not STATS.exists():
        return {"upgrades": 0, "retirements": 0, "blocked": 0, "queue_processed": 0, "last_actions": []}
    return json.loads(STATS.read_text(encoding="utf-8"))


def _save_stats(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    STATS.write_text(json.dumps(data, indent=2), encoding="utf-8")


def queue_summary() -> dict:
    entries = [e for e in load_shadow() if not e.get("upgraded")]
    stats = _load_stats()
    return {
        "pending_upgrades": len(entries),
        "upgrades": stats.get("upgrades", 0),
        "retirements": stats.get("retirements", 0),
        "blocked": stats.get("blocked", 0),
        "last_actions": stats.get("last_actions", [])[-10:],
    }


def _deadline_exceeded(deadline_monotonic: float | None) -> bool:
    if deadline_monotonic is None:
        return False
    return time.monotonic() >= deadline_monotonic or remaining_seconds(deadline_monotonic) <= 0.0


def process_upgrade_batch(
    *,
    limit: int = 10,
    baseline: float = 0.5,
    progress_callback=None,
    deadline_monotonic: float | None = None,
    init_phase: bool = False,
    generation: int | None = None,
    run_proof: bool = True,
) -> dict:
    """Retest top shadow elites; full promote only when all gates pass."""
    batch_started = time.monotonic()
    item_limit = effective_item_limit(init_phase=init_phase, requested_limit=limit)
    sub_deadline = shadow_upgrade_sub_deadline(deadline_monotonic, init_phase=init_phase)
    defer, defer_reason = should_defer_shadow_upgrade(sub_deadline, init_phase=init_phase)

    record_shadow_upgrade_event(
        step="shadow_upgrade_start",
        status="started",
        generation=generation,
        item_limit=item_limit,
        deadline_monotonic=sub_deadline,
        decision="defer" if defer else "proceed",
        init_phase=init_phase,
        defer_reason=defer_reason,
    )
    if progress_callback:
        progress_callback(
            "shadow_upgrade_start",
            {"limit": item_limit, "init_phase": init_phase, "defer": defer, "reason": defer_reason},
        )

    if defer:
        record_shadow_upgrade_event(
            step="shadow_upgrade_deferred",
            status="deferred",
            generation=generation,
            item_limit=item_limit,
            deadline_monotonic=sub_deadline,
            decision=SHADOW_UPGRADE_DEFERRED_DEADLINE,
            error_message_sanitized=defer_reason,
        )
        if progress_callback:
            progress_callback(
                "shadow_upgrade_deferred",
                {"reason": defer_reason, "classification": SHADOW_UPGRADE_DEFERRED_DEADLINE},
            )
        return {
            "processed": 0,
            "upgraded": 0,
            "retired": 0,
            "blocked": 0,
            "deferred": True,
            "classification": SHADOW_UPGRADE_DEFERRED_DEADLINE,
            "defer_reason": defer_reason,
            "command_count": 0,
            "max_item_duration_ms": 0.0,
            "slowest_item_id": "",
            "slowest_item_type": "",
            "items_deferred": 0,
            "items_skipped": 0,
            **queue_summary(),
        }

    entries = sorted(
        [e for e in load_shadow() if not e.get("upgraded")],
        key=lambda e: float(e.get("score") or 0),
        reverse=True,
    )[: min(item_limit, 100)]
    rows_read = len(entries)

    if init_phase and not run_proof:
        record_shadow_upgrade_event(
            step="shadow_upgrade_deferred",
            status="deferred",
            generation=generation,
            rows_read_if_known=rows_read,
            deadline_monotonic=sub_deadline,
            decision=SHADOW_UPGRADE_DEFERRED_DEADLINE,
            error_message_sanitized="init_phase_run_proof_disabled",
        )
        return {
            "processed": 0,
            "upgraded": 0,
            "retired": 0,
            "blocked": 0,
            "deferred": True,
            "classification": SHADOW_UPGRADE_DEFERRED_DEADLINE,
            "defer_reason": "init_phase_run_proof_disabled",
            "command_count": 0,
            "max_item_duration_ms": 0.0,
            "slowest_item_id": "",
            "slowest_item_type": "",
            "items_deferred": rows_read,
            "items_skipped": rows_read,
            **queue_summary(),
        }

    stats = _load_stats()
    upgraded = 0
    blocked = 0
    retired = 0
    actions: list[str] = []
    processed = 0
    items_deferred = 0
    items_skipped = 0
    max_item_duration_ms = 0.0
    slowest_item_id = ""
    partial = False
    classification = "SHADOW_UPGRADE_OK"

    for idx, e in enumerate(entries, start=1):
        if _deadline_exceeded(sub_deadline):
            record_shadow_upgrade_event(
                step="shadow_upgrade_deadline_low",
                status="deferred",
                generation=generation,
                item_index=idx,
                item_limit=item_limit,
                deadline_monotonic=sub_deadline,
                decision=SHADOW_UPGRADE_DEFERRED_DEADLINE,
            )
            actions.append("deadline_reached")
            items_deferred += len(entries) - idx + 1
            partial = True
            classification = SHADOW_UPGRADE_PARTIAL
            break

        rem = remaining_seconds(sub_deadline)
        if rem is not None and rem < 2.0:
            record_shadow_upgrade_event(
                step="shadow_upgrade_deadline_low",
                status="deferred",
                generation=generation,
                item_index=idx,
                item_limit=item_limit,
                deadline_monotonic=sub_deadline,
                decision=SHADOW_UPGRADE_DEFERRED_DEADLINE,
            )
            items_deferred += len(entries) - idx + 1
            partial = True
            classification = SHADOW_UPGRADE_PARTIAL
            break

        cid = e["candidate_id"]
        item_type = "shadow_upgrade_item"

        record_shadow_upgrade_event(
            step="shadow_upgrade_item_start",
            status="started",
            generation=generation,
            item_id=cid,
            item_type=item_type,
            item_index=idx,
            item_limit=item_limit,
            deadline_monotonic=sub_deadline,
        )
        if progress_callback:
            progress_callback(
                "shadow_upgrade_item_start",
                {"completed": idx - 1, "total": len(entries), "candidate_id": cid, "item_index": idx},
            )

        if _deadline_exceeded(sub_deadline):
            items_skipped += 1
            continue

        enqueue(
            cid,
            score=float(e.get("score") or 0),
            reason="shadow_elite_upgrade",
            generation=int(e.get("generation") or 0),
        )

        if _deadline_exceeded(sub_deadline):
            items_skipped += 1
            partial = True
            classification = SHADOW_UPGRADE_PARTIAL
            break

        timeout_seconds = effective_item_timeout_seconds(sub_deadline, init_phase=init_phase)
        item_timeout_ms = timeout_seconds * 1000.0
        started = time.monotonic()
        result = run_process_one_guarded(
            cid,
            baseline=baseline,
            timeout_seconds=timeout_seconds,
            generation=int(e.get("generation") or 0),
            phase="shadow_upgrade_item",
        )
        duration_ms = round((time.monotonic() - started) * 1000.0, 2)
        result["duration_ms"] = duration_ms
        processed += 1

        if result.get("outcome") == "proof_timeout" or duration_ms >= item_timeout_ms - 50:
            record_shadow_upgrade_event(
                step="shadow_upgrade_item_timeout",
                status="timeout",
                generation=generation,
                item_id=cid,
                item_type=item_type,
                item_index=idx,
                item_limit=item_limit,
                deadline_monotonic=sub_deadline,
                item_timeout_ms=item_timeout_ms,
                duration_ms=duration_ms,
                db_path=str(METRICS_DB),
                decision=SHADOW_UPGRADE_ITEM_TIMEOUT,
            )
            partial = True
            classification = SHADOW_UPGRADE_PARTIAL

        if duration_ms >= max_item_duration_ms:
            max_item_duration_ms = duration_ms
            slowest_item_id = cid

        if result.get("outcome") == "proof_ready":
            upgraded += 1
            actions.append(f"upgraded:{cid}")
        elif result.get("outcome") in {"proof_failed", "proof_timeout", "proof_error"}:
            fails = increment_failed_attempts(cid)
            if fails >= 5:
                from doofus.evolution.shadow_elite_retester import retire_failed_shadow

                retire_failed_shadow(cid)
                retired += 1
                actions.append(f"retired:{cid}")
            else:
                blocked += 1
                actions.append(f"blocked:{cid}:{result.get('outcome')}")
        else:
            blocked += 1
            actions.append(f"partial:{cid}")

        record_shadow_upgrade_event(
            step="shadow_upgrade_item_end",
            status="ok",
            generation=generation,
            item_id=cid,
            item_type=item_type,
            item_index=idx,
            item_limit=item_limit,
            deadline_monotonic=sub_deadline,
            duration_ms=duration_ms,
            rows_written_if_known=1,
            db_path=str(METRICS_DB),
            decision=str(result.get("outcome")),
        )
        if progress_callback:
            progress_callback(
                "shadow_upgrade_item_complete",
                {
                    "completed": idx,
                    "total": len(entries),
                    "candidate_id": cid,
                    "outcome": result.get("outcome"),
                    "duration_ms": duration_ms,
                },
            )
            progress_callback(
                "shadow_upgrade_item_end",
                {
                    "completed": idx,
                    "total": len(entries),
                    "candidate_id": cid,
                    "outcome": result.get("outcome"),
                    "duration_ms": duration_ms,
                },
            )

        if _deadline_exceeded(sub_deadline):
            items_deferred += len(entries) - idx
            partial = True
            classification = SHADOW_UPGRADE_PARTIAL
            break

    if partial and classification == SHADOW_UPGRADE_PARTIAL:
        record_shadow_upgrade_event(
            step="shadow_upgrade_partial_result",
            status="partial",
            generation=generation,
            item_limit=item_limit,
            deadline_monotonic=sub_deadline,
            duration_ms=round((time.monotonic() - batch_started) * 1000.0, 2),
            rows_read_if_known=rows_read,
            decision=SHADOW_UPGRADE_PARTIAL,
        )

    stats["upgrades"] = int(stats.get("upgrades", 0)) + upgraded
    stats["retirements"] = int(stats.get("retirements", 0)) + retired
    stats["blocked"] = int(stats.get("blocked", 0)) + blocked
    stats["queue_processed"] = int(stats.get("queue_processed", 0)) + processed
    stats.setdefault("last_actions", []).extend(actions)
    stats["last_actions"] = stats["last_actions"][-50:]
    _save_stats(stats)

    record_shadow_upgrade_event(
        step="shadow_upgrade_end",
        status="ok" if not partial else "partial",
        generation=generation,
        item_limit=item_limit,
        deadline_monotonic=sub_deadline,
        duration_ms=round((time.monotonic() - batch_started) * 1000.0, 2),
        rows_read_if_known=rows_read,
        rows_written_if_known=processed,
        db_path=str(METRICS_DB),
        decision=classification,
    )
    if progress_callback:
        progress_callback(
            "shadow_upgrade_end",
            {
                "processed": processed,
                "partial": partial,
                "classification": classification,
                "items_deferred": items_deferred,
            },
        )

    return {
        "processed": processed,
        "upgraded": upgraded,
        "retired": retired,
        "blocked": blocked,
        "deferred": False,
        "partial": partial,
        "classification": classification,
        "command_count": processed,
        "max_item_duration_ms": max_item_duration_ms,
        "slowest_item_id": slowest_item_id,
        "slowest_item_type": "shadow_upgrade_item" if slowest_item_id else "",
        "items_deferred": items_deferred,
        "items_skipped": items_skipped,
        **queue_summary(),
    }
