"""Route live model calls to the correct provider adapter."""
from __future__ import annotations

import os
from typing import Any

from doofus.core.doofus_env_loader import load_doofus_env
from doofus.model_router.cursor_composer_adapter import CursorComposerAdapter
from doofus.model_router.openai_adapter import OpenAIAdapter
from doofus.model_router.openrouter_adapter import propose_mutations as openrouter_propose
from doofus.model_router.provider_router import resolve_provider
from doofus.model_router.deepseek_v4_flash_adapter import DeepSeekV4FlashAdapter


def propose_mutations(context: dict[str, Any]) -> dict[str, Any]:
    load_doofus_env()
    explicit = os.environ.get("DOOFUS_MODEL_PROVIDER", "").strip().lower()
    route = resolve_provider()
    provider = route.get("provider_selected", "dry_run")
    use_cursor = provider == "cursor" or explicit == "cursor"
    if use_cursor:
        result = CursorComposerAdapter.from_env().propose_mutations(context)
        if (
            result.get("classification") not in ("DOOFUS_MODEL_LIVE", "DOOFUS_MODEL_DRY_RUN")
            and os.environ.get("DOOFUS_CURSOR_HYBRID_FALLBACK", "0") == "1"
            and os.environ.get("DOOFUS_PROVIDER_FALLBACKS_DISABLED", "1") != "1"
        ):
            fallback = openrouter_propose(context)
            fallback["cursor_fallback_from"] = result.get("classification")
            try:
                from doofus.model_router.model_call_ledger import record_model_event

                record_model_event(
                    generation=int(context.get("generation") or 0),
                    model_result={**result, "provider": "cursor"},
                    proposals_applied=0,
                    proposal_valid=False,
                )
            except Exception:
                pass
            return fallback
        result["provider"] = "cursor"
        return result
    if provider == "openai":
        return OpenAIAdapter.from_env().propose_mutations(context)
    if provider == "openrouter":
        return openrouter_propose(context)
    if provider == "dry_run" or not route.get("live_provider_ready"):
        return DeepSeekV4FlashAdapter.from_env().propose_mutations(context)
    return {"classification": "DOOFUS_PROVIDER_BLOCKED", "mode": "blocked", "provider": provider}
