"""Structured telemetry for pre-candidate cycle initialization."""
from __future__ import annotations

import os
from typing import Any

from doofus.core.atomic_json import append_jsonl
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import STATE

EVENTS = STATE / "cycle_init_events.jsonl"

INIT_STEPS = (
    "cycle_init_start",
    "cycle_init_checkpoint_start",
    "cycle_init_checkpoint_end",
    "cycle_init_provider_gate_start",
    "cycle_init_provider_gate_end",
    "cycle_init_provider_readiness_start",
    "cycle_init_provider_readiness_end",
    "cycle_init_db_prepare_start",
    "cycle_init_db_prepare_end",
    "cycle_init_champion_defense_start",
    "cycle_init_champion_defense_end",
    "cycle_init_candidate_generation_start",
    "cycle_init_timeout",
    "cycle_init_abort",
    "cycle_init_cleanup_start",
    "cycle_init_cleanup_end",
)


def cycle_init_timeout_seconds() -> float:
    return float(os.environ.get("DOOFUS_CYCLE_INIT_TIMEOUT_SECONDS", "180"))


def cycle_init_timeout_ms() -> float:
    return cycle_init_timeout_seconds() * 1000.0


def record_cycle_init_event(
    *,
    step: str,
    status: str,
    generation: int,
    phase: str = "init",
    duration_ms: float | None = None,
    timeout_ms: float | None = None,
    checkpoint_generation: int | None = None,
    checkpoint_phase: str | None = None,
    stop_requested: bool | None = None,
    provider: str | None = None,
    model: str | None = None,
    live_mode: bool | None = None,
    one_cycle_approved: bool | None = None,
    db_path: str | None = None,
    active_transaction: bool | None = None,
    rows_written_if_known: int | None = None,
    decision: str = "",
    error_type: str = "",
    error_message_sanitized: str = "",
    extra: dict[str, Any] | None = None,
) -> dict:
    row: dict[str, Any] = {
        "timestamp": utc_now(),
        "generation": int(generation),
        "phase": phase,
        "step": step,
        "status": status,
        "duration_ms": None if duration_ms is None else round(float(duration_ms), 2),
        "timeout_ms": None if timeout_ms is None else round(float(timeout_ms), 2),
        "checkpoint_generation": checkpoint_generation,
        "checkpoint_phase": checkpoint_phase,
        "stop_requested": stop_requested,
        "provider": provider,
        "model": model,
        "live_mode": live_mode,
        "one_cycle_approved": one_cycle_approved,
        "db_path": db_path,
        "active_transaction": active_transaction,
        "rows_written_if_known": rows_written_if_known,
        "decision": decision or None,
        "error_type": error_type or None,
        "error_message_sanitized": (error_message_sanitized or "")[:500] or None,
    }
    if extra:
        row["detail"] = extra
    try:
        append_jsonl(EVENTS, row)
    except RuntimeError:
        if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("DOOFUS_ALLOW_LIVE_RUNTIME_TESTS", "0") != "1":
            return row
        raise
    return row
