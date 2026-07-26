"""Provider-aware model gate."""
from __future__ import annotations

from doofus.model_router.provider_router import resolve_provider
from doofus.supervisor.live_model_cycle_gate import may_call_model


def may_call_live_provider(*, live_requested: bool = True) -> dict:
    route = resolve_provider()
    base = may_call_model(live_requested=live_requested)
    if not route.get("live_provider_ready"):
        return {**base, "allowed": False, "reason": "no_live_provider", "provider": route.get("provider_selected")}
    if route.get("provider_selected") == "blocked":
        return {**base, "allowed": False, "reason": route.get("provider_reason"), "provider": "blocked"}
    return {**base, "provider": route.get("provider_selected"), "model_name": route.get("model_name")}
