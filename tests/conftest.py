"""Global test fixtures — isolate machine credentials."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from doofus.core import doofus_paths
from doofus.core.doofus_state import init_db

_ISOLATED_KEYS = (
    "OPENROUTER_API_KEY",
    "DOOFUS_OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "DOOFUS_OPENAI_API_KEY",
    "DOOFUS_MODEL_PROVIDER",
    "DOOFUS_AUTH_REPAIR_TRY_DESKTOP_SECRET",
)

LIVE_PATH_ATTRS = ("STATE", "RUNTIME", "CONTROL", "LOGS", "HEARTBEATS", "METRICS_DB")


def redirect_live_bindings(patcher) -> list[str]:
    """Repoint every loaded doofus module attr still bound under the live
    runtime at the (already-patched) doofus_paths equivalents.

    Modules that do `from doofus.core.doofus_paths import STATE` copy the path
    at import time, so patching doofus_paths alone is not enough. Call after
    doofus_paths itself has been redirected. Returns what was redirected."""
    import sys

    canonical_runtime = str(doofus_paths.CANONICAL_RUNTIME).lower()
    redirected = []
    for name, mod in list(sys.modules.items()):
        if not name.startswith("doofus") or mod is None:
            continue
        for attr in LIVE_PATH_ATTRS:
            bound = getattr(mod, attr, None)
            if isinstance(bound, Path) and str(bound).lower().startswith(canonical_runtime):
                patcher.setattr(mod, attr, getattr(doofus_paths, attr), raising=False)
                redirected.append(f"{name}.{attr}")
    return redirected


@pytest.fixture(autouse=True)
def _isolate_machine_secrets(monkeypatch, tmp_path):
    """Prevent machine-level keys from leaking into unit tests."""
    # Point the loader at a nonexistent .env so every caller is neutered, even
    # modules that bound load_doofus_env via `from ... import` at import time.
    monkeypatch.setattr("doofus.core.doofus_env_loader.ENV_FILE", tmp_path / "no-such.env")
    monkeypatch.setattr("doofus.core.doofus_env_loader.load_doofus_env", lambda: False)
    monkeypatch.setattr("doofus.model_router.unified_secret_resolver.get_desktop_secret_value", lambda: None)
    monkeypatch.setattr("doofus.model_router.unified_secret_resolver._read_user_env", lambda _n: None)
    monkeypatch.setattr(
        "doofus.model_router.unified_secret_resolver.load_desktop_secret",
        lambda: {"secret_found": False, "key_shape": "unknown", "secret_value": "REDACTED"},
    )
    monkeypatch.setattr("doofus.model_router.unified_secret_resolver._read_gitignored_env", lambda: {})
    for k in _ISOLATED_KEYS:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture(autouse=True)
def _isolate_runtime_paths(tmp_path, monkeypatch):
    """Redirect runtime/state/report paths away from the live workspace."""
    test_root = tmp_path / "doofus_test_root"
    runtime = test_root / "runtime"
    control = runtime / "control"
    state = runtime / "state"
    heartbeats = runtime / "heartbeats"
    logs = runtime / "logs"
    artifacts = test_root / "artifacts" / "latest"
    proof = test_root / "proof_snapshots"
    shared = tmp_path / "shared"
    metrics_db = state / "doofus_metrics.sqlite"

    for p in (runtime, control, state, heartbeats, logs, artifacts, proof, shared):
        p.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DOOFUS_ALLOW_LIVE_RUNTIME_TESTS", "0")

    monkeypatch.setattr(doofus_paths, "ROOT", test_root)
    monkeypatch.setattr(doofus_paths, "RUNTIME", runtime)
    monkeypatch.setattr(doofus_paths, "CONTROL", control)
    monkeypatch.setattr(doofus_paths, "STATE", state)
    monkeypatch.setattr(doofus_paths, "HEARTBEATS", heartbeats)
    monkeypatch.setattr(doofus_paths, "LOGS", logs)
    monkeypatch.setattr(doofus_paths, "ARTIFACTS", artifacts)
    monkeypatch.setattr(doofus_paths, "PROOF", proof)
    monkeypatch.setattr(doofus_paths, "SHARED", shared)
    monkeypatch.setattr(doofus_paths, "METRICS_DB", metrics_db)
    monkeypatch.setattr(doofus_paths, "RUN_ENABLED", control / "DOOFUS_RUN.enabled")
    monkeypatch.setattr(doofus_paths, "STOP_REQUEST", control / "DOOFUS_STOP.request")
    monkeypatch.setattr(doofus_paths, "EMERGENCY_STOP", control / "DOOFUS_EMERGENCY_STOP.request")

    import doofus.core.doofus_state as ds
    import doofus.dashboard.dashboard_data as dashboard_data
    import doofus.dashboard.live_dashboard_refresh as live_dashboard_refresh
    import doofus.dashboard.live_data_api as live_data_api
    import doofus.dashboard.live_metric_queries as live_metric_queries
    import doofus.dashboard.promotion_quality_panel as promotion_quality_panel
    import doofus.evaluation.candidate_quality as candidate_quality
    import doofus.evaluation.promotion_near_miss as promotion_near_miss
    import doofus.evolution.best_ever_ledger as bel
    import doofus.evolution.elite_archive_maintainer as elite_archive_maintainer
    import doofus.evolution.evolution_quality_analyzer as evolution_quality_analyzer
    import doofus.evolution.shadow_elite_upgrade_queue as shadow_elite_upgrade_queue
    import doofus.reports.burn_in_metrics_snapshot as burn_in_metrics_snapshot
    import doofus.reports.proof_builder_handoff_report as proof_builder_handoff_report
    import doofus.scoring.promotion_audit as promotion_audit
    import doofus.scoring.twelve_hour_promotion_audit as twelve_hour_promotion_audit
    import doofus.evolution.branch_retirement as branch_retirement
    import doofus.evolution.challenger_tournament as challenger_tournament
    import doofus.evolution.elite_archive as elite_archive
    import doofus.evolution.map_elites_archive as mea
    import doofus.evolution.shadow_elite_archive as shadow_elite_archive
    import doofus.evolution.shadow_elite_parent_selector as shadow_elite_parent_selector
    import doofus.evolution.shadow_elite_retirement as shadow_elite_retirement
    import doofus.evolution.shadow_elite_to_full_promotion as shadow_elite_to_full_promotion
    import doofus.evolution.adaptive_mutation_pressure as adaptive_mutation_pressure
    import doofus.meta.aevolve.algorithm_selector as algorithm_selector
    import doofus.meta.codeevolve.param_overrides as codeevolve_param_overrides
    import doofus.meta.codeevolve.project_registry as codeevolve_project_registry
    import doofus.meta.gep.capsule_store as gep_capsule_store
    import doofus.meta.gep.event_emitter as gep_event_emitter
    import doofus.meta.gepa.prompt_store as gepa_prompt_store
    import doofus.meta.gepa.trace_collector as gepa_trace_collector
    import doofus.meta.recursive_supervisor as recursive_supervisor
    import doofus.model_router.cursor_agent_cli as cursor_agent_cli
    import doofus.promotion.tier3_final_gate as tier3_gate
    import doofus.proof.high_score_rejection_miner as high_score_rejection_miner
    import doofus.proof.high_score_rescue_loop as high_score_rescue_loop
    import doofus.proof.proof_builder_runner as proof_builder_runner
    import doofus.proof.proof_builder_queue as proof_builder_queue
    import doofus.reports.sota_kpi_tracker as kpi
    import doofus.runtime.process_registry as process_registry
    import doofus.runtime.safe_cleanup as safe_cleanup
    import doofus.runtime.session_cleanup as session_cleanup
    import doofus.runtime.runtime_health as runtime_health
    import doofus.runtime.runtime_repair as runtime_repair
    import doofus.runtime.windows_runtime_manager as windows_runtime_manager
    import doofus.scoring.proof_threshold_sweep as proof_threshold_sweep
    import doofus.scoring.promotion_quarantine as promotion_quarantine
    import doofus.safety.budget_guard as budget_guard
    import doofus.supervisor.heartbeat_watchdog as heartbeat_watchdog
    import doofus.supervisor.doofus_crash_recovery as crash_recovery
    import doofus.supervisor.doofus_cycle_checkpoint as cycle_checkpoint
    import doofus.supervisor.live_cycle_launch_guard as live_cycle_launch_guard
    import doofus.supervisor.supervisor_phase_watchdog as supervisor_phase_watchdog
    import doofus.supervisor.process_singleton as process_singleton

    monkeypatch.setattr(ds, "STATE", state)
    monkeypatch.setattr(ds, "METRICS_DB", metrics_db)
    monkeypatch.setattr(dashboard_data, "METRICS_DB", metrics_db)
    monkeypatch.setattr(budget_guard, "METRICS_DB", metrics_db)
    # Sweep every loaded doofus module: any import-time binding that still points
    # into the live workspace gets redirected to the tmp equivalents. This closes
    # the whole class of leaks (a test once COUNT(*)-scanned the live 39 GB
    # metrics DB via an unpatched binding). Enforced by test_no_live_db_bindings.
    redirect_live_bindings(monkeypatch)
    monkeypatch.setattr(crash_recovery, "CHECKPOINT", state / "last_checkpoint.json")
    monkeypatch.setattr(bel, "STATE", state)
    monkeypatch.setattr(bel, "LEDGER", state / "best_ever_ledger.json")
    monkeypatch.setattr(branch_retirement, "RETIRED", state / "retired_branches.json")
    monkeypatch.setattr(challenger_tournament, "TOURNAMENT", state / "challenger_tournaments.json")
    monkeypatch.setattr(elite_archive, "ARCHIVE", state / "elite_archive.json")
    monkeypatch.setattr(elite_archive, "USAGE", state / "elite_archive_usage.json")
    monkeypatch.setattr(mea, "ARCHIVE_JSON", state / "map_elites_archive.json")
    monkeypatch.setattr(shadow_elite_archive, "ARCHIVE", state / "shadow_elite_archive.json")
    monkeypatch.setattr(shadow_elite_parent_selector, "ARCHIVE", state / "shadow_elite_archive.json")
    monkeypatch.setattr(shadow_elite_retirement, "ARCHIVE", state / "shadow_elite_archive.json")
    monkeypatch.setattr(shadow_elite_retirement, "FAILURES", state / "shadow_elite_failures.json")
    monkeypatch.setattr(shadow_elite_to_full_promotion, "AUDIT", state / "shadow_elite_upgrade_audit.json")
    monkeypatch.setattr(adaptive_mutation_pressure, "STATE_FILE", state / "evolution_pressure_state.json")
    monkeypatch.setattr(algorithm_selector, "STATS_FILE", state / "aevolve" / "algorithm_stats.json")
    monkeypatch.setattr(codeevolve_param_overrides, "OVERRIDES_FILE", state / "codeevolve" / "overrides.json")
    monkeypatch.setattr(codeevolve_project_registry, "PROJECTS_FILE", state / "codeevolve" / "projects.json")
    monkeypatch.setattr(gep_capsule_store, "CAPSULES_FILE", state / "gep" / "capsules.json")
    monkeypatch.setattr(gep_event_emitter, "EVENTS_FILE", state / "gep" / "events.jsonl")
    monkeypatch.setattr(recursive_supervisor, "META_STATE_FILE", state / "meta_evolution_state.json")
    monkeypatch.setattr(gepa_trace_collector, "TRACE_DIR", state / "gepa")
    monkeypatch.setattr(gepa_trace_collector, "TRACE_JSONL", state / "gepa" / "traces.jsonl")
    monkeypatch.setattr(gepa_prompt_store, "PROMPT_DIR", state / "gepa" / "prompts")
    monkeypatch.setattr(cursor_agent_cli, "AGENT_WORKSPACE_DIR", runtime / "cursor-agent-cli-workspace")
    monkeypatch.setattr(tier3_gate, "TIER3_STATE", state / "tier3_finals.json")
    monkeypatch.setattr(tier3_gate, "TIER3_RESULTS", state / "tier3" / "results.jsonl")
    monkeypatch.setattr(high_score_rejection_miner, "METRICS_DB", metrics_db)
    monkeypatch.setattr(high_score_rescue_loop, "INLINE_RESCUE_EVENTS", state / "inline_rescue_events.jsonl")
    monkeypatch.setattr(proof_builder_runner, "METRICS_DB", metrics_db)
    monkeypatch.setattr(proof_builder_queue, "QUEUE_FILE", state / "proof_builder_queue.json")
    monkeypatch.setattr(proof_builder_queue, "STATS_FILE", state / "proof_builder_stats.json")
    monkeypatch.setattr(proof_builder_queue, "EVENTS_FILE", state / "proof_builder_queue_events.jsonl")
    monkeypatch.setattr(proof_threshold_sweep, "METRICS_DB", metrics_db)
    monkeypatch.setattr(runtime_health, "MANAGER_STATE", state / "runtime_manager_state.json")
    monkeypatch.setattr(process_registry, "REGISTRY", state / "process_registry.json")
    monkeypatch.setattr(safe_cleanup, "LAST", state / "safe_cleanup_last.json")
    monkeypatch.setattr(session_cleanup, "LAST", state / "session_cleanup_last.json")
    monkeypatch.setattr(session_cleanup, "SCHEDULER_PID_FILE", state / "autopilot_scheduler.pid")
    monkeypatch.setattr(runtime_repair, "REPAIR_LOG", state / "runtime_repair_log.json")
    monkeypatch.setattr(runtime_repair, "REPAIR_LOCK", state / "runtime_repair.lock")
    monkeypatch.setattr(windows_runtime_manager, "STATE_FILE", state / "runtime_manager_state.json")
    monkeypatch.setattr(promotion_quarantine, "DEBT_FILE", state / "promotion_debt.json")
    monkeypatch.setattr(process_singleton, "STATE", state)
    monkeypatch.setattr(cycle_checkpoint, "CHECKPOINT", state / "cycle_checkpoint.json")
    monkeypatch.setattr(live_cycle_launch_guard, "EVENTS", state / "live_cycle_launch_guard_events.jsonl")
    monkeypatch.setattr(supervisor_phase_watchdog, "EVENTS", state / "supervisor_phase_events.jsonl")
    monkeypatch.setattr(heartbeat_watchdog, "METRICS_DB", metrics_db)
    monkeypatch.setattr(heartbeat_watchdog, "HEARTBEATS", heartbeats)

    monkeypatch.setattr(kpi, "STATE", state)
    monkeypatch.setattr(kpi, "SHARED", shared)
    monkeypatch.setattr(kpi, "METRICS_DB", metrics_db)
    monkeypatch.setattr(kpi, "KPI_STATE", state / "kpi_tracker.json")
    monkeypatch.setattr(kpi, "KPI_HISTORY", state / "kpi_history.jsonl")
    monkeypatch.setattr(kpi, "HOURLY_LAST", state / "hourly_kpi_last.json")
    monkeypatch.setattr(kpi, "HOURLY_REPORT_DIR", shared / "hourly-kpi-reports")
    monkeypatch.setattr(kpi, "HOURLY_LATEST_MD", shared / "DOOFUS-HOURLY-KPI-LATEST.md")
    monkeypatch.setattr(kpi, "HOURLY_LATEST_JSON", shared / "DOOFUS-HOURLY-KPI-LATEST.json")

    init_db(metrics_db)


def pytest_collection_modifyitems(config, items):
    if os.environ.get("DOOFUS_ALLOW_LIVE_RUNTIME_TESTS") == "1":
        return
    skip_live = pytest.mark.skip(reason="live runtime tests require DOOFUS_ALLOW_LIVE_RUNTIME_TESTS=1")
    for item in items:
        if "live_runtime" in item.keywords:
            item.add_marker(skip_live)
