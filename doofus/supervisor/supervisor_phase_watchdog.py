"""Supervisor phase telemetry and timeout helpers."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from doofus.core.atomic_json import append_jsonl
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import STATE
from doofus.supervisor.process_singleton import read_singleton_pid

EVENTS = STATE / "supervisor_phase_events.jsonl"

_DEFAULT_TIMEOUTS = {
    "inline_rescue": 180.0,
    "candidate_generation": 60.0,
    "model_call": 120.0,
    "scoring": 300.0,
    "kpi_refresh": 60.0,
}


@dataclass
class SupervisorPhaseTimeout(RuntimeError):
    phase: str
    duration_ms: float
    limit_seconds: float

    def __str__(self) -> str:
        return (
            f"phase {self.phase} exceeded {self.limit_seconds:.1f}s "
            f"(duration_ms={self.duration_ms:.2f})"
        )


def _timeout_env_key(phase: str) -> str:
    return f"DOOFUS_PHASE_TIMEOUT_{phase.upper()}"


def phase_timeout_seconds(phase: str) -> float:
    return float(os.environ.get(_timeout_env_key(phase), _DEFAULT_TIMEOUTS.get(phase, 120.0)))


def record_phase_event(
    *,
    generation: int,
    phase: str,
    status: str,
    phase_started_at: str,
    phase_ended_at: str,
    duration_ms: float,
    timeout: bool = False,
    error_type: str = "",
    error_message_sanitized: str = "",
    checkpoint_before: dict | None = None,
    checkpoint_after: dict | None = None,
    heartbeat_age_ms: float | None = None,
    lock_owner_pid: int | None = None,
    repair_action: str = "",
) -> dict:
    row = {
        "timestamp_utc": utc_now(),
        "generation": generation,
        "phase": phase,
        "phase_started_at": phase_started_at,
        "phase_ended_at": phase_ended_at,
        "duration_ms": round(duration_ms, 2),
        "status": status,
        "timeout": bool(timeout),
        "error_type": error_type or None,
        "error_message_sanitized": (error_message_sanitized or "")[:500] or None,
        "checkpoint_before": checkpoint_before or {},
        "checkpoint_after": checkpoint_after or {},
        "heartbeat_age_ms": None if heartbeat_age_ms is None else round(float(heartbeat_age_ms), 2),
        "lock_owner_pid": lock_owner_pid,
        "repair_action": repair_action or None,
    }
    append_jsonl(EVENTS, row)
    return row


def finalize_phase_or_raise(
    *,
    generation: int,
    phase: str,
    phase_started_at: str,
    phase_ended_at: str,
    duration_ms: float,
    checkpoint_before: dict | None = None,
    checkpoint_after: dict | None = None,
    heartbeat_age_ms: float | None = None,
) -> dict:
    limit = phase_timeout_seconds(phase)
    if duration_ms > limit * 1000.0:
        row = record_phase_event(
            generation=generation,
            phase=phase,
            status="timeout",
            timeout=True,
            phase_started_at=phase_started_at,
            phase_ended_at=phase_ended_at,
            duration_ms=duration_ms,
            checkpoint_before=checkpoint_before,
            checkpoint_after=checkpoint_after,
            heartbeat_age_ms=heartbeat_age_ms,
            lock_owner_pid=read_singleton_pid("doofus_supervisor"),
            error_type="SupervisorPhaseTimeout",
            error_message_sanitized=f"{phase} exceeded {limit:.1f}s",
        )
        raise SupervisorPhaseTimeout(phase=phase, duration_ms=duration_ms, limit_seconds=limit)
    return record_phase_event(
        generation=generation,
        phase=phase,
        status="ok",
        phase_started_at=phase_started_at,
        phase_ended_at=phase_ended_at,
        duration_ms=duration_ms,
        checkpoint_before=checkpoint_before,
        checkpoint_after=checkpoint_after,
        heartbeat_age_ms=heartbeat_age_ms,
        lock_owner_pid=read_singleton_pid("doofus_supervisor"),
    )


def record_child_timeout(
    *,
    generation: int,
    phase: str,
    timeout_seconds: float,
    detail: str,
    checkpoint_before: dict | None = None,
) -> dict:
    now = utc_now()
    return record_phase_event(
        generation=generation,
        phase=phase,
        status="child_timeout",
        timeout=True,
        phase_started_at=now,
        phase_ended_at=now,
        duration_ms=timeout_seconds * 1000.0,
        error_type="ChildProcessTimeout",
        error_message_sanitized=detail,
        checkpoint_before=checkpoint_before,
        checkpoint_after=checkpoint_before,
        lock_owner_pid=read_singleton_pid("doofus_supervisor"),
        repair_action="child_terminated",
    )


def record_lock_cleanup(
    *,
    generation: int,
    phase: str,
    detail: str,
    repaired: bool,
) -> dict:
    now = utc_now()
    return record_phase_event(
        generation=generation,
        phase=phase,
        status="stale_lock_recovered" if repaired else "stale_lock_left_intact",
        phase_started_at=now,
        phase_ended_at=now,
        duration_ms=0.0,
        checkpoint_before={},
        checkpoint_after={},
        lock_owner_pid=read_singleton_pid("doofus_supervisor"),
        repair_action=detail,
    )
