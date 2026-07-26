"""Live dashboard data API — stable JSON-like snapshots."""
from __future__ import annotations
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from doofus.core.doofus_config import DoofusConfig
from doofus.core.doofus_paths import SHARED, METRICS_DB, ROOT
from doofus.core.doofus_state import init_db
from doofus.dashboard import live_metric_queries as mq
from doofus.dashboard.live_state_reader import read_control_state, read_checkpoint_status, read_latest_error
from doofus.dashboard.live_task_reader import get_task_status as read_scheduled_tasks
from doofus.model_router.model_environment_probe import probe_model_environment
from doofus.model_router.model_secret_redactor import redact_secrets
from doofus.safety.budget_guard import check_budget
from doofus.safety.secret_guard import key_present
from doofus.dashboard.dashboard_data import summary
from doofus.dashboard.live_burn_in_panel import get_burn_in_status
from doofus.dashboard.promotion_audit_panel import get_promotion_audit_status
from doofus.dashboard.evolution_pressure_panel import get_evolution_pressure_panel
from doofus.dashboard.elite_archive_panel import get_elite_archive_panel
from doofus.dashboard.promotion_quality_panel import get_promotion_quality_panel
from doofus.dashboard.supervisor_reliability_panel import get_supervisor_reliability_panel
from doofus.dashboard.twelve_hour_run_panel import get_twelve_hour_run_panel
from doofus.dashboard.evolution_quality_panel import get_evolution_quality_panel
from doofus.dashboard.twelve_hour_promotion_audit_panel import get_twelve_hour_promotion_audit_panel
from doofus.dashboard.proof_builder_panel import get_proof_builder_panel
from doofus.dashboard.shadow_elite_panel import get_shadow_elite_panel
from doofus.dashboard.threshold_tuning_panel import get_threshold_tuning_panel
from doofus.dashboard.conversion_panel import get_conversion_panel
from doofus.dashboard.full_autonomy_panel import get_full_autonomy_panel
from doofus.dashboard.inline_rescue_panel import get_inline_rescue_panel
from doofus.dashboard.elite_compounding_panel import get_elite_compounding_panel
from doofus.dashboard.watchdog_panel import get_watchdog_panel
from doofus.dashboard.dashboard_health_panel import get_dashboard_health_panel
from doofus.dashboard.shadow_elite_upgrade_panel import get_shadow_elite_upgrade_panel
from doofus.dashboard.elite_archive_growth_panel import get_elite_archive_growth_panel
from doofus.dashboard.runtime_manager_panel import get_runtime_manager_panel
from doofus.dashboard.full_functionality_panel import get_full_functionality_panel
from doofus.dashboard.supervisor_health_panel import get_supervisor_health_panel
from doofus.dashboard.meta_evolution_panel import get_meta_evolution_panel
from doofus.dashboard.metacognition_panel import get_metacognition_panel

DEFAULT_LIMIT = 200
_fast_status_cache: dict = {"at": 0.0, "data": None}
_FAST_STATUS_TTL = 8.0
_limit = DEFAULT_LIMIT

def set_query_limit(n: int) -> None:
    global _limit
    _limit = max(100, min(1000, int(n)))

def get_query_limit() -> int:
    return _limit

def _git_head() -> str:
    try:
        head_file = ROOT / ".git" / "HEAD"
        if not head_file.exists():
            return "unknown"
        ref = head_file.read_text(encoding="utf-8").strip()
        if ref.startswith("ref:"):
            ref_path = ROOT / ".git" / ref.split(":", 1)[1].strip()
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()[:12]
            return ref.split("/")[-1][:12]
        return ref[:12]
    except Exception:
        return "unknown"

def _heartbeat_age_seconds() -> float | None:
    hb = mq.recent_heartbeats(1)
    if not hb:
        return None
    try:
        ts = datetime.fromisoformat(hb[0]["created_at"].replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
    except Exception:
        return None

def get_model_auth_status(*, fast: bool = False) -> dict:
    from doofus.model_router.provider_router import resolve_provider

    env = probe_model_environment(live_probe=not fast)
    route = resolve_provider()
    provider = route.get("provider_selected", "dry_run")
    key_ok = bool(env.get("any_key_present") or env.get("openai_api_key_present") or env.get("openrouter_api_key_present"))
    mode = env.get("model_mode", "dry_run")
    probed = env.get("provider_auth")
    status_code = env.get("provider_status_code", 0)

    if not key_ok:
        provider_auth = "no_key"
        summary_text = "No API key loaded — dry-run mode"
    elif mode == "dry_run" and provider == "dry_run":
        provider_auth = "dry_run"
        summary_text = "No live provider selected — dry-run mode"
    elif probed in ("ok", "rate_limited"):
        provider_auth = "ok" if probed == "ok" else "rate_limited"
        summary_text = f"Live provider {provider} auth OK" if probed == "ok" else f"Live provider {provider} rate limited (HTTP 429) — auth accepted"
    elif probed == "failing" or status_code == 401:
        provider_auth = "failing"
        summary_text = f"Provider {provider} rejected credentials (HTTP {status_code or 401})"
    elif route.get("live_provider_ready"):
        provider_auth = "pending"
        summary_text = f"Provider {provider} selected — awaiting confirmation"
    else:
        provider_auth = "blocked"
        summary_text = f"Provider {provider} blocked; DeepSeek lane: {route.get('deepseek_lane_status')}"

    proof_rows = [e for e in mq.recent_dashboard_events(20) if e.get("event_type") == "live_model_proof"]
    live_proof = proof_rows[0].get("detail", "")[:120] if proof_rows else "none"
    last_calls = mq.recent_model_calls(3)
    last_call_provider = last_calls[0].get("provider") if last_calls else "none"

    return {
        "key_present": key_ok,
        "provider_auth": provider_auth,
        "auth_status": provider_auth,
        "model_mode": mode,
        "provider_selected": provider,
        "active_model": route.get("model_name"),
        "live_provider_ready": route.get("live_provider_ready", False),
        "deepseek_openrouter_ready": route.get("deepseek_openrouter_ready", False),
        "deepseek_lane_status": route.get("deepseek_lane_status", "auth_required"),
        "active_auth_source": env.get("auth_source_name", "missing"),
        "auth_source_path": env.get("auth_source_path", ""),
        "key_shape": route.get("key_shape", "unknown"),
        "secret_length_bucket": env.get("secret_length_bucket", "unknown"),
        "last_provider_status_code": status_code,
        "last_provider_status": redact_secrets(summary_text)[:200],
        "last_provider_error_class": route.get("safe_error_class", "none"),
        "last_live_cycle_provider": last_call_provider,
        "auth_summary": summary_text,
        "live_proof_result": live_proof,
        "note": "Provider routing active — secret REDACTED.",
    }

def _operation_label(sw: dict) -> str:
    if sw.get("emergency_stop"):
        return "EMERGENCY STOP — clear emergency then Start"
    if sw.get("stop_requested"):
        return "STOPPED — stop file active"
    if not sw.get("run_enabled"):
        return "IDLE — click Start to enable DOOFUS_RUN.enabled"
    if sw.get("may_run"):
        return "RUNNING — supervisor may cycle"
    return "BLOCKED"

def get_budget_rate_status() -> dict:
    cfg = DoofusConfig.from_env()
    b = check_budget(cfg)
    return {
        **b,
        "budget_remaining_usd": max(0.0, cfg.max_daily_cost_usd - float(b.get("daily_cost_est", 0))),
        "calls_remaining_hour": max(0, cfg.max_model_calls_per_hour - int(b.get("calls_last_hour", 0))),
    }

def get_status_cards(*, fast: bool = False) -> dict:
    import time as _time
    if fast:
        now = _time.time()
        cached = _fast_status_cache.get("data")
        if cached and now - float(_fast_status_cache.get("at", 0)) < _FAST_STATUS_TTL:
            return cached
    s = summary(fast=fast)
    sw = read_control_state()
    auth = get_model_auth_status(fast=fast)
    budget = get_budget_rate_status()
    hb_age = _heartbeat_age_seconds()
    cp = read_checkpoint_status()
    gen = cp.get("legacy_checkpoint", {}).get("generation", s.get("generation", 0))
    hb_status = "fresh" if hb_age is not None and hb_age < 120 else "stale" if hb_age is not None else "none"
    result = {
        "operation_state": _operation_label(sw),
        "may_run": sw.get("may_run", False),
        "run_enabled": sw.get("run_enabled", False),
        "stop_requested": sw.get("stop_requested", False),
        "emergency_stop_active": sw.get("emergency_stop", False),
        "current_generation": gen,
        "total_candidates": s.get("candidate_count", 0),
        "total_mutations": s.get("mutation_count", 0),
        "total_promoted": s.get("promotion_count", 0),
        "total_rejected": s.get("rejection_count", 0),
        "model_mode": auth.get("model_mode"),
        "model_auth_status": auth.get("provider_auth"),
        "auth_summary": auth.get("auth_summary"),
        "hourly_model_calls": budget.get("calls_last_hour", 0),
        "daily_estimated_cost": budget.get("daily_cost_est", 0),
        "budget_remaining": budget.get("budget_remaining_usd", 0),
        "heartbeat_age_seconds": hb_age,
        "heartbeat_status": hb_status,
        "latest_error": read_latest_error() or "none",
        "latest_report_path": str(SHARED),
        "git_head": _git_head(),
    }
    if fast:
        _fast_status_cache["at"] = _time.time()
        _fast_status_cache["data"] = result
    return result

def get_live_counters() -> dict:
    return {
        "candidates": mq.count_table("candidates"),
        "promotions": mq.count_table("promotions"),
        "rejections": mq.count_table("rejections"),
        "mutations": mq.count_table("mutations"),
        "model_calls": mq.count_table("model_calls"),
        "cycles": mq.count_table("cycles"),
        "safety_events": mq.count_table("safety_events"),
        "heartbeats": mq.count_table("heartbeats"),
    }

def get_cycle_timeseries() -> list[dict]:
    return mq.recent_cycles(_limit)

def get_candidate_generation_timeseries() -> list[dict]:
    return mq.score_by_generation(_limit)

def get_variant_mutant_timeseries() -> dict:
    cycles = mq.recent_cycles(_limit)
    gens = [c.get("generation", 0) for c in reversed(cycles)]
    return {"variants_by_cycle": gens, "mutants_tested": mq.count_table("candidates")}

def get_score_timeseries() -> list[dict]:
    return mq.score_by_generation(_limit)

def get_compounding_timeseries() -> list[dict]:
    return [{"generation": r["generation"], "value": r.get("avg_compounding", 0)} for r in mq.score_by_generation(_limit)]

def get_recursive_learning_timeseries() -> list[dict]:
    return [{"generation": r["generation"], "value": r.get("avg_recursive", 0)} for r in mq.score_by_generation(_limit)]

def get_promotion_rejection_timeseries() -> dict:
    return {
        "promotions": mq.promotions_over_time(_limit),
        "rejections": mq.rejections_over_time(_limit),
    }

def get_rejection_reason_counts() -> list[dict]:
    return mq.rejection_reason_counts(_limit)

def get_model_call_timeseries() -> list[dict]:
    return mq.model_calls_timeseries(_limit)

def get_arena_result_matrix() -> list[dict]:
    return mq.arena_results(_limit)

def get_candidate_lineage_rows() -> list[dict]:
    return mq.lineage_rows(_limit)

def get_recent_candidates() -> list[dict]:
    return mq.recent_candidates(min(50, _limit))

def get_recent_promotions() -> list[dict]:
    return mq.recent_promotions(min(50, _limit))

def get_recent_rejections() -> list[dict]:
    return mq.recent_rejections(min(50, _limit))

def get_safety_events() -> list[dict]:
    return mq.recent_safety_events(min(50, _limit))

def get_heartbeat_status() -> dict:
    hb = mq.recent_heartbeats(10)
    return {"recent": hb, "age_seconds": _heartbeat_age_seconds()}

def get_checkpoint_status() -> dict:
    return read_checkpoint_status()

def get_task_status() -> dict:
    return read_scheduled_tasks()

def get_latest_report_paths() -> list[str]:
    paths = []
    if SHARED.exists():
        for p in sorted(SHARED.glob("DOOFUS-*"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
            paths.append(str(p))
    return paths

def get_dashboard_snapshot(*, fast: bool = False) -> dict:
    try:
        if not fast:
            init_db()
        db_ok = METRICS_DB.exists()
    except Exception:
        db_ok = False
    return {
        "classification": "B1010_LIVE_DASHBOARD_DATA_API_READY",
        "status": "snapshot_ok",
        "db_ok": db_ok,
        "cards": get_status_cards(fast=fast),
        "counters": get_live_counters(),
        "model_auth": get_model_auth_status(fast=fast),
        "budget_rate": get_budget_rate_status(),
        "tasks": get_task_status(),
        "burn_in": get_burn_in_status(),
        "promotion_audit": get_promotion_audit_status(),
        "evolution": get_evolution_pressure_panel(),
        "elite_archive": get_elite_archive_panel(),
        "promotion_quality": get_promotion_quality_panel(),
        "supervisor_reliability": get_supervisor_reliability_panel(),
        "twelve_hour_run": get_twelve_hour_run_panel(),
        "evolution_quality": get_evolution_quality_panel(),
        "twelve_hour_promotion_audit": get_twelve_hour_promotion_audit_panel(),
        "proof_builder": get_proof_builder_panel(),
        "shadow_elite": get_shadow_elite_panel(),
        "threshold_tuning": get_threshold_tuning_panel(),
        "conversion": get_conversion_panel(),
        "full_autonomy": get_full_autonomy_panel(),
        "inline_rescue": get_inline_rescue_panel(),
        "elite_compounding": get_elite_compounding_panel(),
        "watchdog": get_watchdog_panel(),
        "dashboard_health": get_dashboard_health_panel(),
        "shadow_elite_upgrade": get_shadow_elite_upgrade_panel(),
        "elite_archive_growth": get_elite_archive_growth_panel(),
        "runtime_manager": get_runtime_manager_panel(),
        "full_functionality": get_full_functionality_panel(),
        "supervisor_health": get_supervisor_health_panel(),
        "meta_evolution": get_meta_evolution_panel(),
        "metacognition": get_metacognition_panel(),
        "query_limit": get_query_limit(),
        "dunce_handoff_untouched": True,
        "bind": "127.0.0.1:8765",
    }
