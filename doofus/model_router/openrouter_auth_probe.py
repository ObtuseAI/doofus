"""Simple OpenRouter auth probe wrapper."""
from __future__ import annotations

from doofus.model_router.openrouter_auth_config import ensure_auth_loaded, get_api_key_for_request
from doofus.model_router.openrouter_provider_probe import probe_chat


def probe_current_auth() -> dict:
    ensure_auth_loaded()
    key, source = get_api_key_for_request()
    if not key:
        return {"provider_auth": "missing", "source": source, "status_code": 0}
    result = probe_chat(key)
    return {
        "provider_auth": "ok" if result.get("ok") else "failing",
        "source": source,
        **result,
    }
