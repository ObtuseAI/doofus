"""Utilities for running Doofus logic against an isolated runtime copy."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Iterator

from doofus.core import doofus_paths
from doofus.core.doofus_state import init_db


@dataclass(frozen=True)
class IsolatedRuntime:
    root: Path
    runtime: Path
    control: Path
    state: Path
    heartbeats: Path
    logs: Path
    artifacts: Path
    proof: Path
    shared: Path
    metrics_db: Path


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        dst.mkdir(parents=True, exist_ok=True)
        return
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dst)


def _copy_state_without_live_db(src_state: Path, dst_state: Path) -> None:
    dst_state.mkdir(parents=True, exist_ok=True)
    if not src_state.exists():
        return
    skip_names = {
        "doofus_metrics.sqlite",
        "doofus_metrics.sqlite-shm",
        "doofus_metrics.sqlite-wal",
    }
    for entry in src_state.iterdir():
        if entry.name in skip_names:
            continue
        target = dst_state / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, target)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)


class _PatchSet:
    def __init__(self) -> None:
        self._items: list[tuple[object, str, object]] = []

    def set(self, obj: object, attr: str, value: object) -> None:
        self._items.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, value)

    def undo(self) -> None:
        for obj, attr, value in reversed(self._items):
            setattr(obj, attr, value)
        self._items.clear()


class _EnvPatchSet:
    def __init__(self) -> None:
        self._items: list[tuple[str, str | None]] = []

    def set(self, key: str, value: str) -> None:
        self._items.append((key, os.environ.get(key)))
        os.environ[key] = value

    def undo(self) -> None:
        for key, previous in reversed(self._items):
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
        self._items.clear()


@contextmanager
def isolated_runtime_copy(
    *,
    source_root: Path | None = None,
    clear_stop_flags: bool = True,
) -> Iterator[IsolatedRuntime]:
    source_root = source_root or doofus_paths.CANONICAL_ROOT
    temp_root = Path(tempfile.mkdtemp(prefix="doofus_isolated_"))
    runtime = temp_root / "runtime"
    control = runtime / "control"
    state = runtime / "state"
    heartbeats = runtime / "heartbeats"
    logs = runtime / "logs"
    artifacts = temp_root / "artifacts" / "latest"
    proof = temp_root / "proof_snapshots"
    shared = temp_root / "shared"
    metrics_db = state / "doofus_metrics.sqlite"

    _copy_state_without_live_db(source_root / "runtime" / "state", state)
    _copy_tree(source_root / "runtime" / "control", control)
    heartbeats.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    proof.mkdir(parents=True, exist_ok=True)
    shared.mkdir(parents=True, exist_ok=True)

    if clear_stop_flags:
        _touch(control / "DOOFUS_RUN.enabled")
        stop_request = control / "DOOFUS_STOP.request"
        emergency_stop = control / "DOOFUS_EMERGENCY_STOP.request"
        if stop_request.exists():
            stop_request.unlink()
        if emergency_stop.exists():
            emergency_stop.unlink()

    patches = _PatchSet()
    env_patches = _EnvPatchSet()

    # Core paths.
    patches.set(doofus_paths, "RUNTIME", runtime)
    patches.set(doofus_paths, "CONTROL", control)
    patches.set(doofus_paths, "STATE", state)
    patches.set(doofus_paths, "HEARTBEATS", heartbeats)
    patches.set(doofus_paths, "LOGS", logs)
    patches.set(doofus_paths, "ARTIFACTS", artifacts)
    patches.set(doofus_paths, "PROOF", proof)
    patches.set(doofus_paths, "SHARED", shared)
    patches.set(doofus_paths, "METRICS_DB", metrics_db)
    patches.set(doofus_paths, "RUN_ENABLED", control / "DOOFUS_RUN.enabled")
    patches.set(doofus_paths, "STOP_REQUEST", control / "DOOFUS_STOP.request")
    patches.set(doofus_paths, "EMERGENCY_STOP", control / "DOOFUS_EMERGENCY_STOP.request")

    env_patches.set("DOOFUS_ROOT", str(temp_root))
    env_patches.set("DOOFUS_SHARED", str(shared))
    env_patches.set("DOOFUS_ARTIFACTS", str(artifacts))
    env_patches.set("DOOFUS_PROOF", str(proof))
    env_patches.set("DOOFUS_RUNTIME", str(runtime))
    env_patches.set("DOOFUS_CONTROL", str(control))
    env_patches.set("DOOFUS_LOGS", str(logs))
    env_patches.set("DOOFUS_STATE", str(state))
    env_patches.set("DOOFUS_HEARTBEATS", str(heartbeats))
    env_patches.set("DOOFUS_METRICS_DB", str(metrics_db))
    env_patches.set("DOOFUS_RUN_ENABLED", str(control / "DOOFUS_RUN.enabled"))
    env_patches.set("DOOFUS_STOP_REQUEST", str(control / "DOOFUS_STOP.request"))
    env_patches.set("DOOFUS_EMERGENCY_STOP", str(control / "DOOFUS_EMERGENCY_STOP.request"))

    # Import lazily after primary path patching.
    import doofus.core.doofus_state as doofus_state
    import doofus.core.pipeline_log as pipeline_log
    import doofus.dashboard.dashboard_data as dashboard_data
    import doofus.evolution.adaptive_mutation_pressure as adaptive_mutation_pressure
    import doofus.evolution.best_ever_ledger as best_ever_ledger
    import doofus.evolution.branch_retirement as branch_retirement
    import doofus.evolution.challenger_tournament as challenger_tournament
    import doofus.evolution.elite_archive as elite_archive
    import doofus.evolution.map_elites_archive as map_elites_archive
    import doofus.evolution.shadow_elite_archive as shadow_elite_archive
    import doofus.evolution.shadow_elite_parent_selector as shadow_elite_parent_selector
    import doofus.evolution.shadow_elite_retirement as shadow_elite_retirement
    import doofus.evolution.shadow_elite_to_full_promotion as shadow_elite_to_full_promotion
    import doofus.meta.aevolve.algorithm_selector as algorithm_selector
    import doofus.meta.codeevolve.param_overrides as codeevolve_param_overrides
    import doofus.meta.gep.capsule_store as gep_capsule_store
    import doofus.meta.gep.event_emitter as gep_event_emitter
    import doofus.meta.gepa.prompt_store as gepa_prompt_store
    import doofus.meta.gepa.trace_collector as gepa_trace_collector
    import doofus.meta.recursive_supervisor as recursive_supervisor
    import doofus.model_router.cursor_agent_cli as cursor_agent_cli
    import doofus.promotion.tier3_final_gate as tier3_gate
    import doofus.proof.high_score_rejection_miner as high_score_rejection_miner
    import doofus.proof.high_score_rescue_loop as high_score_rescue_loop
    import doofus.proof.proof_builder_queue as proof_builder_queue
    import doofus.proof.proof_builder_runner as proof_builder_runner
    import doofus.reports.sota_kpi_tracker as kpi
    import doofus.runtime.process_registry as process_registry
    import doofus.runtime.runtime_health as runtime_health
    import doofus.runtime.runtime_repair as runtime_repair
    import doofus.runtime.safe_cleanup as safe_cleanup
    import doofus.runtime.session_cleanup as session_cleanup
    import doofus.runtime.windows_runtime_manager as windows_runtime_manager
    import doofus.scoring.proof_threshold_sweep as proof_threshold_sweep
    import doofus.scoring.promotion_quarantine as promotion_quarantine
    import doofus.safety.budget_guard as budget_guard
    import doofus.supervisor.doofus_crash_recovery as crash_recovery
    import doofus.supervisor.doofus_cycle_checkpoint as cycle_checkpoint
    import doofus.supervisor.heartbeat_watchdog as heartbeat_watchdog
    import doofus.supervisor.live_cycle_launch_guard as live_cycle_launch_guard
    import doofus.supervisor.process_singleton as process_singleton
    import doofus.supervisor.supervisor_phase_watchdog as supervisor_phase_watchdog

    patches.set(doofus_state, "STATE", state)
    patches.set(doofus_state, "METRICS_DB", metrics_db)
    patches.set(dashboard_data, "METRICS_DB", metrics_db)
    patches.set(budget_guard, "METRICS_DB", metrics_db)
    patches.set(crash_recovery, "CHECKPOINT", state / "last_checkpoint.json")
    patches.set(best_ever_ledger, "STATE", state)
    patches.set(best_ever_ledger, "LEDGER", state / "best_ever_ledger.json")
    patches.set(branch_retirement, "RETIRED", state / "retired_branches.json")
    patches.set(challenger_tournament, "TOURNAMENT", state / "challenger_tournaments.json")
    patches.set(elite_archive, "ARCHIVE", state / "elite_archive.json")
    patches.set(elite_archive, "USAGE", state / "elite_archive_usage.json")
    patches.set(map_elites_archive, "ARCHIVE_JSON", state / "map_elites_archive.json")
    patches.set(shadow_elite_archive, "ARCHIVE", state / "shadow_elite_archive.json")
    patches.set(shadow_elite_parent_selector, "ARCHIVE", state / "shadow_elite_archive.json")
    patches.set(shadow_elite_retirement, "ARCHIVE", state / "shadow_elite_archive.json")
    patches.set(shadow_elite_retirement, "FAILURES", state / "shadow_elite_failures.json")
    patches.set(shadow_elite_to_full_promotion, "AUDIT", state / "shadow_elite_upgrade_audit.json")
    patches.set(adaptive_mutation_pressure, "STATE_FILE", state / "evolution_pressure_state.json")
    patches.set(algorithm_selector, "STATS_FILE", state / "aevolve" / "algorithm_stats.json")
    patches.set(codeevolve_param_overrides, "OVERRIDES_FILE", state / "codeevolve" / "overrides.json")
    patches.set(gep_capsule_store, "CAPSULES_FILE", state / "gep" / "capsules.json")
    patches.set(gep_event_emitter, "EVENTS_FILE", state / "gep" / "events.jsonl")
    patches.set(recursive_supervisor, "META_STATE_FILE", state / "meta_evolution_state.json")
    patches.set(gepa_trace_collector, "TRACE_DIR", state / "gepa")
    patches.set(gepa_trace_collector, "TRACE_JSONL", state / "gepa" / "traces.jsonl")
    patches.set(gepa_prompt_store, "PROMPT_DIR", state / "gepa" / "prompts")
    patches.set(cursor_agent_cli, "AGENT_WORKSPACE_DIR", runtime / "cursor-agent-cli-workspace")
    patches.set(tier3_gate, "TIER3_STATE", state / "tier3_finals.json")
    patches.set(tier3_gate, "TIER3_RESULTS", state / "tier3" / "results.jsonl")
    patches.set(high_score_rejection_miner, "METRICS_DB", metrics_db)
    patches.set(high_score_rescue_loop, "INLINE_RESCUE_EVENTS", state / "inline_rescue_events.jsonl")
    patches.set(proof_builder_runner, "METRICS_DB", metrics_db)
    patches.set(proof_builder_queue, "QUEUE_FILE", state / "proof_builder_queue.json")
    patches.set(proof_builder_queue, "STATS_FILE", state / "proof_builder_stats.json")
    patches.set(proof_builder_queue, "EVENTS_FILE", state / "proof_builder_queue_events.jsonl")
    patches.set(proof_threshold_sweep, "METRICS_DB", metrics_db)
    patches.set(runtime_health, "MANAGER_STATE", state / "runtime_manager_state.json")
    patches.set(process_registry, "REGISTRY", state / "process_registry.json")
    patches.set(safe_cleanup, "LAST", state / "safe_cleanup_last.json")
    patches.set(session_cleanup, "LAST", state / "session_cleanup_last.json")
    patches.set(session_cleanup, "SCHEDULER_PID_FILE", state / "autopilot_scheduler.pid")
    patches.set(runtime_repair, "REPAIR_LOG", state / "runtime_repair_log.json")
    patches.set(runtime_repair, "REPAIR_LOCK", state / "runtime_repair.lock")
    patches.set(windows_runtime_manager, "STATE_FILE", state / "runtime_manager_state.json")
    patches.set(promotion_quarantine, "DEBT_FILE", state / "promotion_debt.json")
    patches.set(process_singleton, "STATE", state)
    patches.set(cycle_checkpoint, "CHECKPOINT", state / "cycle_checkpoint.json")
    patches.set(live_cycle_launch_guard, "EVENTS", state / "live_cycle_launch_guard_events.jsonl")
    patches.set(supervisor_phase_watchdog, "EVENTS", state / "supervisor_phase_events.jsonl")
    patches.set(heartbeat_watchdog, "METRICS_DB", metrics_db)
    patches.set(heartbeat_watchdog, "HEARTBEATS", heartbeats)

    patches.set(kpi, "STATE", state)
    patches.set(kpi, "SHARED", shared)
    patches.set(kpi, "METRICS_DB", metrics_db)
    patches.set(kpi, "KPI_STATE", state / "kpi_tracker.json")
    patches.set(kpi, "KPI_HISTORY", state / "kpi_history.jsonl")
    patches.set(kpi, "HOURLY_LAST", state / "hourly_kpi_last.json")
    patches.set(kpi, "HOURLY_REPORT_DIR", shared / "hourly-kpi-reports")
    patches.set(kpi, "HOURLY_LATEST_MD", shared / "DOOFUS-HOURLY-KPI-LATEST.md")
    patches.set(kpi, "HOURLY_LATEST_JSON", shared / "DOOFUS-HOURLY-KPI-LATEST.json")

    original_handlers = list(pipeline_log.log.handlers)
    original_logs = pipeline_log.LOGS
    new_handler = logging.FileHandler(logs / "pipeline.log", encoding="utf-8")
    new_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    patches.set(pipeline_log, "LOGS", logs)
    for handler in original_handlers:
        pipeline_log.log.removeHandler(handler)
    pipeline_log.log.addHandler(new_handler)

    try:
        init_db(metrics_db)
        yield IsolatedRuntime(
            root=temp_root,
            runtime=runtime,
            control=control,
            state=state,
            heartbeats=heartbeats,
            logs=logs,
            artifacts=artifacts,
            proof=proof,
            shared=shared,
            metrics_db=metrics_db,
        )
    finally:
        pipeline_log.log.removeHandler(new_handler)
        new_handler.close()
        for handler in original_handlers:
            pipeline_log.log.addHandler(handler)
        patches.set(pipeline_log, "LOGS", original_logs)
        env_patches.undo()
        patches.undo()
