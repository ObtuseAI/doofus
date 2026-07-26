"""Pre-candidate init watchdog - bounded stall detection and safe baseline rollback."""
from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypeVar

from doofus.core import doofus_paths
from doofus.runtime.live_db_preflight import inspect_live_db
from doofus.safety.on_off_switch import status as switch_status, stop as switch_stop
from doofus.supervisor.cycle_init_telemetry import (
    cycle_init_timeout_ms,
    cycle_init_timeout_seconds,
    record_cycle_init_event,
)
from doofus.supervisor.doofus_crash_recovery import load_checkpoint, save_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint, write_checkpoint as write_cycle_ck


@dataclass
class CycleInitTimeout(RuntimeError):
    step: str
    duration_ms: float
    limit_ms: float

    def __str__(self) -> str:
        return (
            f"cycle init step {self.step} exceeded {self.limit_ms:.0f}ms "
            f"(duration_ms={self.duration_ms:.2f})"
        )


@dataclass
class CycleInitContext:
    generation: int
    baseline_checkpoint: dict
    run_id: str
    dry_run: bool
    live_model_if_available: bool
    model_mode: str
    provider: str = ""
    model_name: str = ""
    one_cycle_approved: bool = False
    db_path: Path | None = None
    _started_perf: float = field(default_factory=time.perf_counter, init=False)
    _step_started_perf: float = field(default_factory=time.perf_counter, init=False)
    _current_step: str = "cycle_init_start"
    _candidate_generation_started: bool = False
    _model_calls: int = 0
    _had_candidates: bool = False
    _abort_result: dict[str, Any] = field(default_factory=dict)

    def resolved_db_path(self) -> Path:
        return self.db_path or doofus_paths.METRICS_DB

    def __enter__(self) -> CycleInitContext:
        self._started_perf = time.perf_counter()
        self._emit("cycle_init_start", "started")
        return self

    def __exit__(self, exc_type, exc, _tb) -> bool:
        if exc_type is CycleInitTimeout:
            self._abort(exc)
            return False
        if exc_type is None and not self._candidate_generation_started:
            self._emit("cycle_init_abort", "incomplete_without_candidate_generation", decision="unexpected_exit")
        return False

    @property
    def limit_ms(self) -> float:
        return cycle_init_timeout_ms()

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._started_perf) * 1000.0

    def step_elapsed_ms(self) -> float:
        return (time.perf_counter() - self._step_started_perf) * 1000.0

    def check(self, step: str | None = None) -> None:
        if self._candidate_generation_started:
            return
        if step:
            self._current_step = step
        elapsed = self.elapsed_ms()
        if elapsed > self.limit_ms:
            raise CycleInitTimeout(step=self._current_step, duration_ms=elapsed, limit_ms=self.limit_ms)

    def step_start(self, step: str) -> None:
        self.check()
        self._current_step = step
        self._step_started_perf = time.perf_counter()
        cp = load_checkpoint()
        stop = switch_status()
        self._emit(
            step,
            "started",
            checkpoint_generation=int(cp.get("generation", -1)),
            checkpoint_phase=str(cp.get("phase") or ""),
            stop_requested=bool(stop.get("stop_requested")),
            provider=self.provider or None,
            model=self.model_name or None,
        )

    def step_end(self, step: str, **fields: Any) -> None:
        cp = load_checkpoint()
        stop = switch_status()
        duration = self.step_elapsed_ms()
        emit_fields = dict(fields)
        emit_fields.pop("checkpoint_generation", None)
        emit_fields.pop("checkpoint_phase", None)
        emit_fields.pop("stop_requested", None)
        emit_fields.pop("provider", None)
        emit_fields.pop("model", None)
        self._emit(
            step,
            "ok",
            duration_ms=duration,
            checkpoint_generation=int(cp.get("generation", -1)),
            checkpoint_phase=str(cp.get("phase") or ""),
            stop_requested=bool(stop.get("stop_requested")),
            provider=self.provider or None,
            model=self.model_name or None,
            **emit_fields,
        )
        self.check()

    def mark_candidate_generation_started(self) -> None:
        self._candidate_generation_started = True
        self.step_start("cycle_init_candidate_generation_start")

    def mark_model_call(self) -> None:
        self._model_calls += 1

    def mark_candidates_created(self) -> None:
        self._had_candidates = True

    def _emit(self, step: str, status: str, **fields: Any) -> None:
        cp = load_checkpoint()
        filtered = dict(fields)
        for key in (
            "checkpoint_generation",
            "checkpoint_phase",
            "stop_requested",
            "provider",
            "model",
            "live_mode",
            "one_cycle_approved",
            "db_path",
        ):
            filtered.pop(key, None)
        record_cycle_init_event(
            step=step,
            status=status,
            generation=self.generation,
            timeout_ms=self.limit_ms,
            live_mode=self.live_model_if_available and not self.dry_run,
            one_cycle_approved=self.one_cycle_approved,
            db_path=str(self.resolved_db_path()),
            checkpoint_generation=int(cp.get("generation", -1)),
            checkpoint_phase=str(cp.get("phase") or ""),
            **filtered,
        )

    def _abort(self, exc: CycleInitTimeout) -> dict[str, Any]:
        self._emit(
            "cycle_init_timeout",
            "timeout",
            duration_ms=exc.duration_ms,
            error_type="CycleInitTimeout",
            error_message_sanitized=str(exc),
            decision="abort",
        )
        self._emit("cycle_init_cleanup_start", "started")
        cleanup = rollback_init_without_progress(
            generation=self.generation,
            baseline_checkpoint=self.baseline_checkpoint,
            had_candidates=self._had_candidates,
            model_calls=self._model_calls,
            stalled_step=exc.step,
            db_path=self.resolved_db_path(),
        )
        stop_after = switch_stop()
        self._emit(
            "cycle_init_cleanup_end",
            "ok",
            decision=cleanup.get("classification"),
            stop_requested=bool(stop_after.get("stop_requested")),
            extra=cleanup,
        )
        self._abort_result = {
            "classification": "DOOFUS_CYCLE_INIT_TIMEOUT_ABORTED",
            "stalled_step": exc.step,
            "duration_ms": exc.duration_ms,
            "limit_ms": exc.limit_ms,
            "cleanup": cleanup,
            "stop_restored": bool(stop_after.get("stop_requested")),
        }
        return self._abort_result

    def build_timeout_result(self, exc: CycleInitTimeout, *, inline_rescue_result: dict | None = None) -> dict:
        if not self._abort_result:
            self._abort(exc)
        from doofus.reports.live_cycle_reporter import build_live_cycle_report

        return build_live_cycle_report(
            {
                "classification": "DOOFUS_CYCLE_INIT_TIMEOUT_ABORTED",
                "run_id": self.run_id,
                "generation": self.generation,
                "candidates": 0,
                "promoted": 0,
                "shadow_promoted": 0,
                "rejected": 0,
                "partial": True,
                "evolution": {},
                "compounding": {},
                "inline_rescue": inline_rescue_result or {},
                "baseline_score": float(self.baseline_checkpoint.get("baseline_score", 0.5)),
                "lineage": [],
                "lineage_parents": 0,
                "model_mode": self.model_mode,
                "model_result": {"classification": "DOOFUS_MODEL_SKIPPED", "init_timeout": True},
                "dry_run": self.dry_run,
                "live_model_if_available": self.live_model_if_available,
                "gate": {},
                "init_timeout": self._abort_result,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
            }
        )["cycle"]


def rollback_init_without_progress(
    *,
    generation: int,
    baseline_checkpoint: dict,
    had_candidates: bool,
    model_calls: int,
    stalled_step: str,
    db_path: Path | None = None,
) -> dict:
    baseline_gen = int(baseline_checkpoint.get("generation", -1))
    can_rollback = not had_candidates and model_calls <= 0
    checkpoint_after = load_checkpoint()
    cycle_ck_before = read_checkpoint()

    rollback_applied = False
    if can_rollback:
        restored = dict(baseline_checkpoint)
        restored["phase"] = "complete"
        save_checkpoint(restored)
        write_cycle_ck(
            cycle_ck_before.get("stage", "cycle_complete"),
            cycle_ck_before.get("data", {"generation": baseline_gen}),
        )
        rollback_applied = True
        checkpoint_after = load_checkpoint()

    db_path = db_path or doofus_paths.METRICS_DB
    pf = inspect_live_db(
        checkpoint_generation=baseline_gen,
        target_generation=generation,
        db_path=db_path,
    )
    partial_rows = int(pf.get("target_generation_total") or 0) + int(pf.get("above_target_generation_total") or 0)
    scrub_plan = None
    if partial_rows > 0:
        scrub_plan = {
            "classification": "DOOFUS_INIT_TIMEOUT_PARTIAL_ROWS_DETECTED",
            "partial_row_count": partial_rows,
            "target_generation": generation,
            "table_counts": pf.get("table_counts", {}),
            "recommended_action": "backup_first_then_scrub_target_generation",
            "script": "scripts/doofus_init_timeout_containment.py",
        }

    return {
        "classification": "DOOFUS_CYCLE_INIT_TIMEOUT_ABORTED",
        "stalled_step": stalled_step,
        "rollback_applied": rollback_applied,
        "baseline_generation": baseline_gen,
        "target_generation": generation,
        "checkpoint_after": checkpoint_after,
        "cycle_checkpoint_after": read_checkpoint(),
        "partial_rows_detected": partial_rows,
        "scrub_plan": scrub_plan,
        "timeout_seconds": cycle_init_timeout_seconds(),
    }


T = TypeVar("T")


def run_bounded_init_call(
    ctx: CycleInitContext,
    *,
    step: str,
    func: Callable[[], T],
    timeout_seconds: float | None = None,
) -> T:
    """Run a potentially blocking init call with a hard thread join timeout."""
    limit = float(timeout_seconds if timeout_seconds is not None else cycle_init_timeout_seconds())
    ctx.check(step)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="doofus-init") as pool:
        future = pool.submit(func)
        try:
            return future.result(timeout=limit)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            raise CycleInitTimeout(
                step=step,
                duration_ms=limit * 1000.0,
                limit_ms=limit * 1000.0,
            ) from exc
