"""Telemetry for high-score rejection miner queries and inline-rescue defer decisions."""
from __future__ import annotations

import time
from typing import Any

from doofus.core.atomic_json import append_jsonl
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import STATE

EVENTS = STATE / "high_score_miner_events.jsonl"


def _remaining_ms(deadline_monotonic: float | None) -> float | None:
    if deadline_monotonic is None:
        return None
    return max(0.0, (deadline_monotonic - time.monotonic()) * 1000.0)


def record_miner_event(
    *,
    step: str,
    status: str,
    generation: int | None = None,
    deadline_monotonic: float | None = None,
    query_name: str | None = None,
    query_duration_ms: float | None = None,
    rows_returned: int | None = None,
    rows_scanned_if_known: int | None = None,
    limit: int | None = None,
    db_path: str | None = None,
    progress_abort_enabled: bool | None = None,
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
        "deadline_remaining_ms": _remaining_ms(deadline_monotonic),
        "query_name": query_name,
        "query_duration_ms": query_duration_ms,
        "rows_returned": rows_returned,
        "rows_scanned_if_known": rows_scanned_if_known,
        "limit": limit,
        "db_path": db_path,
        "progress_abort_enabled": progress_abort_enabled,
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
