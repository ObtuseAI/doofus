"""Probe model environment with provider routing — no secrets."""
from __future__ import annotations

from doofus.core.doofus_config import DoofusConfig
from doofus.core.doofus_env_loader import load_doofus_env
from doofus.model_router.openai_adapter import probe_openai_auth
from doofus.model_router.provider_router import resolve_provider
from doofus.model_router.unified_secret_resolver import resolve_unified_secret
from doofus.safety.secret_guard import assert_no_secret_in_payload


def probe_model_environment(*, live_probe: bool = True) -> dict:
    load_doofus_env()
    cfg = DoofusConfig.from_env()
    route = resolve_provider()
    secret = resolve_unified_secret()
    provider = route.get("provider_selected", "dry_run")
    provider_auth = "missing"
    status_code = 0
    if live_probe:
        if provider == "openai" and route.get("live_provider_ready"):
            probe = probe_openai_auth()
            provider_auth = probe.get("provider_auth", "pending")
            status_code = probe.get("provider_status_code", 0)
        elif provider == "openrouter" and route.get("deepseek_openrouter_ready"):
            from doofus.model_router.openrouter_auth_probe import probe_current_auth
            p = probe_current_auth()
            provider_auth = p.get("provider_auth", "pending")
            status_code = p.get("status_code", 0)
        elif secret.get("secret_found"):
            provider_auth = "pending" if route.get("live_provider_ready") else "blocked"
    elif secret.get("secret_found"):
        provider_auth = "cached" if route.get("live_provider_ready") else "blocked"
    elif route.get("live_provider_ready"):
        provider_auth = "pending"
    return assert_no_secret_in_payload({
        "classification": "DOOFUS_MODEL_ENV_PROBE_READY",
        "openrouter_api_key_present": bool(cfg.openrouter_api_key),
        "openai_api_key_present": bool(cfg.openai_api_key),
        "any_key_present": secret.get("secret_found", False),
        "openrouter_api_key_value": "REDACTED",
        "model_provider": provider,
        "model_name": route.get("model_name"),
        "temperature": cfg.model_temperature,
        "daily_budget_cap": cfg.max_daily_cost_usd,
        "hourly_call_cap": cfg.max_model_calls_per_hour,
        "model_mode": cfg.model_mode,
        "auth_source_name": secret.get("secret_source", "missing"),
        "auth_source_path": secret.get("secret_source_path", ""),
        "key_shape": route.get("key_shape", "unknown"),
        "secret_length_bucket": secret.get("secret_length_bucket", "unknown"),
        "provider_auth": provider_auth,
        "provider_status_code": status_code,
        "live_provider_ready": route.get("live_provider_ready", False),
        "deepseek_openrouter_ready": route.get("deepseek_openrouter_ready", False),
        "deepseek_lane_status": route.get("deepseek_lane_status", "auth_required"),
    })
