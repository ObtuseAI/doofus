"""OpenRouter adapter wrapper — DeepSeek lane only with openrouter_like keys."""
from __future__ import annotations

from typing import Any

from doofus.model_router.deepseek_v4_flash_adapter import DeepSeekV4FlashAdapter
from doofus.model_router.provider_router import resolve_provider


def propose_mutations(context: dict[str, Any]) -> dict[str, Any]:
    route = resolve_provider()
    if route.get("provider_selected") != "openrouter":
        return {
            "classification": "DOOFUS_OPENROUTER_LANE_UNAVAILABLE",
            "mode": "blocked",
            "provider": "openrouter",
            "reason": "deepseek_lane_requires_openrouter_like_key",
            "deepseek_openrouter_ready": False,
        }
    result = DeepSeekV4FlashAdapter.from_env().propose_mutations(context)
    result["provider"] = "openrouter"
    result["deepseek_openrouter_ready"] = result.get("classification") == "DOOFUS_MODEL_LIVE"
    return result
