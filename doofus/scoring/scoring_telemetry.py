"""Low-overhead scoring telemetry for bounded diagnostics."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
import time

from doofus.core import doofus_paths
from doofus.core.atomic_json import append_jsonl
from doofus.core.doofus_events import utc_now
from doofus.model_router.model_secret_redactor import redact_secrets

SCORING_EVENTS_FILE = "scoring_step_events.jsonl"


@dataclass(frozen=True)
class CycleContext:
    generation: int
    cycle_id: str
    candidate_count: int
    batch_id: str
    started_perf: float


@dataclass(frozen=True)
class CandidateContext:
    candidate_id: str
    candidate_index: int
    candidate_count: int
    started_perf: float


@dataclass
class StepContext:
    scorer_name: str
    scorer_module: str
    substep: str
    input_size: int | None = None
    output_size: int | None = None
    cache_hit: bool = False
    sqlite_write_count: int = 0
    artifact_write_count: int = 0
    subprocess_pid: int | None = None
    heartbeat_written: bool = False
    status: str = "ok"
    error_type: str = ""
    error_message_sanitized: str = ""
    started_perf: float = 0.0


_CYCLE: ContextVar[CycleContext | None] = ContextVar("doofus_scoring_cycle", default=None)
_CANDIDATE: ContextVar[CandidateContext | None] = ContextVar("doofus_scoring_candidate", default=None)
_STEP: ContextVar[StepContext | None] = ContextVar("doofus_scoring_step", default=None)


def events_path() -> Path:
    return doofus_paths.STATE / SCORING_EVENTS_FILE


def reset_events_file() -> None:
    path = events_path()
    if path.exists():
        path.unlink()


def bind_cycle(*, generation: int, cycle_id: str, candidate_count: int, batch_id: str = "scoring") -> Token:
    return _CYCLE.set(
        CycleContext(
            generation=generation,
            cycle_id=cycle_id,
            candidate_count=candidate_count,
            batch_id=batch_id,
            started_perf=time.perf_counter(),
        )
    )


def reset_cycle(token: Token) -> None:
    _CYCLE.reset(token)


def bind_candidate(*, candidate_id: str, candidate_index: int, candidate_count: int) -> Token:
    return _CANDIDATE.set(
        CandidateContext(
            candidate_id=candidate_id,
            candidate_index=candidate_index,
            candidate_count=candidate_count,
            started_perf=time.perf_counter(),
        )
    )


def reset_candidate(token: Token) -> None:
    _CANDIDATE.reset(token)


def current_step() -> StepContext | None:
    return _STEP.get()


def _cumulative_cycle_duration_ms() -> float | None:
    cycle = _CYCLE.get()
    if cycle is None:
        return None
    return round((time.perf_counter() - cycle.started_perf) * 1000.0, 2)


def _append(row: dict) -> None:
    try:
        append_jsonl(events_path(), row)
    except Exception:
        # Telemetry must never break the scoring path.
        return


def record_scoring_event(
    *,
    scorer_name: str,
    scorer_module: str,
    substep: str,
    event_type: str,
    duration_ms: float | None = None,
    generation: int | None = None,
    cycle_id: str | None = None,
    candidate_id: str | None = None,
    candidate_index: int | None = None,
    candidate_count: int | None = None,
    batch_id: str | None = None,
    input_size: int | None = None,
    output_size: int | None = None,
    cache_hit: bool = False,
    sqlite_write_count: int = 0,
    artifact_write_count: int = 0,
    subprocess_pid: int | None = None,
    heartbeat_written: bool = False,
    status: str = "ok",
    error_type: str = "",
    error_message_sanitized: str = "",
) -> None:
    cycle = _CYCLE.get()
    candidate = _CANDIDATE.get()
    row = {
        "timestamp_utc": utc_now(),
        "generation": generation if generation is not None else (cycle.generation if cycle else None),
        "cycle_id": cycle_id or (cycle.cycle_id if cycle else ""),
        "candidate_id": candidate_id or (candidate.candidate_id if candidate else ""),
        "scorer_name": scorer_name,
        "scorer_module": scorer_module,
        "substep": substep,
        "event_type": event_type,
        "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
        "cumulative_cycle_duration_ms": _cumulative_cycle_duration_ms(),
        "candidate_index": candidate_index if candidate_index is not None else (candidate.candidate_index if candidate else None),
        "candidate_count": candidate_count if candidate_count is not None else (candidate.candidate_count if candidate else (cycle.candidate_count if cycle else None)),
        "batch_id": batch_id or (cycle.batch_id if cycle else "scoring"),
        "input_size": input_size,
        "output_size": output_size,
        "cache_hit": bool(cache_hit),
        "sqlite_write_count": int(sqlite_write_count),
        "artifact_write_count": int(artifact_write_count),
        "subprocess_pid": subprocess_pid,
        "heartbeat_written": bool(heartbeat_written),
        "status": status,
        "error_type": error_type,
        "error_message_sanitized": redact_secrets(str(error_message_sanitized or ""))[:500],
    }
    _append(row)


def record_progress(
    *,
    scorer_name: str,
    scorer_module: str,
    substep: str,
    heartbeat_written: bool = False,
    status: str = "ok",
    input_size: int | None = None,
    output_size: int | None = None,
) -> None:
    record_scoring_event(
        scorer_name=scorer_name,
        scorer_module=scorer_module,
        substep=substep,
        event_type="progress",
        input_size=input_size,
        output_size=output_size,
        heartbeat_written=heartbeat_written,
        status=status,
    )


def record_timeout(*, error_message_sanitized: str, error_type: str = "Timeout") -> None:
    step = _STEP.get()
    if step is not None:
        duration_ms = (time.perf_counter() - step.started_perf) * 1000.0
        record_scoring_event(
            scorer_name=step.scorer_name,
            scorer_module=step.scorer_module,
            substep=step.substep,
            event_type="timeout",
            duration_ms=duration_ms,
            input_size=step.input_size,
            output_size=step.output_size,
            cache_hit=step.cache_hit,
            sqlite_write_count=step.sqlite_write_count,
            artifact_write_count=step.artifact_write_count,
            subprocess_pid=step.subprocess_pid,
            heartbeat_written=step.heartbeat_written,
            status="timeout",
            error_type=error_type,
            error_message_sanitized=error_message_sanitized,
        )
        return
    record_scoring_event(
        scorer_name="scoring_loop",
        scorer_module="doofus.supervisor.doofus_loop_runner",
        substep="scoring_phase",
        event_type="timeout",
        status="timeout",
        error_type=error_type,
        error_message_sanitized=error_message_sanitized,
    )


@contextmanager
def scoring_step(
    *,
    scorer_name: str,
    scorer_module: str,
    substep: str,
    input_size: int | None = None,
) -> StepContext:
    step = StepContext(
        scorer_name=scorer_name,
        scorer_module=scorer_module,
        substep=substep,
        input_size=input_size,
        started_perf=time.perf_counter(),
    )
    token = _STEP.set(step)
    record_scoring_event(
        scorer_name=scorer_name,
        scorer_module=scorer_module,
        substep=substep,
        event_type="start",
        input_size=input_size,
    )
    try:
        yield step
    except Exception as exc:
        record_scoring_event(
            scorer_name=scorer_name,
            scorer_module=scorer_module,
            substep=substep,
            event_type="error",
            duration_ms=(time.perf_counter() - step.started_perf) * 1000.0,
            input_size=step.input_size,
            output_size=step.output_size,
            cache_hit=step.cache_hit,
            sqlite_write_count=step.sqlite_write_count,
            artifact_write_count=step.artifact_write_count,
            subprocess_pid=step.subprocess_pid,
            heartbeat_written=step.heartbeat_written,
            status="error",
            error_type=type(exc).__name__,
            error_message_sanitized=str(exc),
        )
        raise
    else:
        record_scoring_event(
            scorer_name=scorer_name,
            scorer_module=scorer_module,
            substep=substep,
            event_type="cached" if step.cache_hit else "end",
            duration_ms=(time.perf_counter() - step.started_perf) * 1000.0,
            input_size=step.input_size,
            output_size=step.output_size,
            cache_hit=step.cache_hit,
            sqlite_write_count=step.sqlite_write_count,
            artifact_write_count=step.artifact_write_count,
            subprocess_pid=step.subprocess_pid,
            heartbeat_written=step.heartbeat_written,
            status=step.status,
            error_type=step.error_type,
            error_message_sanitized=step.error_message_sanitized,
        )
    finally:
        _STEP.reset(token)
