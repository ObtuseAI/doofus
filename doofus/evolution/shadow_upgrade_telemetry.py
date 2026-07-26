"""Telemetry for shadow elite upgrade batch and inline-rescue defer decisions."""
from __future__ import annotations

import time
from typing import Any

from doofus.core.atomic_json import append_jsonl
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import STATE

EVENTS = STATE / "shadow_upgrade_events.jsonl"


def _remaining_ms(deadline_monotonic: float | None) -> float | None:
    if deadline_monotonic is None:
        return None
    return max(0.0, (deadline_monotonic - time.monotonic()) * 1000.0)


def record_shadow_upgrade_event(
    *,
    step: str,
    status: str,
    generation: int | None = None,
    item_id: str | None = None,
    item_type: str | None = None,
    item_index: int | None = None,
    item_limit: int | None = None,
    deadline_monotonic: float | None = None,
    item_timeout_ms: float | None = None,
    duration_ms: float | None = None,
    rows_read_if_known: int | None = None,
    rows_written_if_known: int | None = None,
    db_path: str | None = None,
    decision: str | None = None,
    error_type: str | None = None,
    error_message_sanitized: str | None = None,
    **extra: Any,
) -> None:
    payload: dict[str, Any] = {
        "timestamp": utc_now(),
        "generation": generation,
        "step": step,
        "status": status,
        "item_id": item_id,
        "item_type": item_type,
        "item_index": item_index,
        "item_limit": item_limit,
        "deadline_remaining_ms": _remaining_ms(deadline_monotonic),
        "item_timeout_ms": item_timeout_ms,
        "duration_ms": duration_ms,
        "rows_read_if_known": rows_read_if_known,
        "rows_written_if_known": rows_written_if_known,
        "db_path": db_path,
        "decision": decision,
        "error_type": error_type,
        "error_message_sanitized": error_message_sanitized,
    }
    if extra:
        payload["detail"] = extra
    try:
        append_jsonl(EVENTS, payload)
    except RuntimeError as exc:
        if "pytest attempted to write live runtime path" in str(exc):
            return
        raise
