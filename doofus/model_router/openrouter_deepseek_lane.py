"""OpenRouter DeepSeek lane status."""
from __future__ import annotations

from doofus.model_router.openrouter_auth_repair_probe import run_repair_probe
from doofus.model_router.provider_router import resolve_provider
from doofus.safety.secret_guard import assert_no_secret_in_payload


def deepseek_lane_status() -> dict:
    route = resolve_provider()
    ready = bool(route.get("deepseek_openrouter_ready"))
    status = {
        "deepseek_openrouter_ready": ready,
        "deepseek_lane_status": "ready" if ready else "auth_required",
        "provider_selected": route.get("provider_selected"),
        "key_shape": route.get("key_shape"),
        "model_name": route.get("model_name") if ready else "deepseek/deepseek-v4-flash",
    }
    if ready:
        probe = run_repair_probe()
        status["provider_auth"] = probe.get("provider_auth", "pending")
        status["provider_status_code"] = probe.get("attempts", [{}])[0].get("status_code", 0) if probe.get("attempts") else 0
    else:
        status["provider_auth"] = "auth_required"
        status["note"] = "OpenRouter DeepSeek lane requires openrouter_like Desktop key"
    return assert_no_secret_in_payload(status)
