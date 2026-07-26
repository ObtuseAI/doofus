"""OpenRouter auth configuration — no secrets in output."""
from __future__ import annotations

import os

from doofus.core.doofus_config import DoofusConfig
from doofus.model_router.auth_source_resolver import apply_to_process_env, resolve_auth_source

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_AUTH_KEY_URL = "https://openrouter.ai/api/v1/auth/key"
REPAIR_ENV_FLAG = "DOOFUS_AUTH_REPAIR_TRY_DESKTOP_SECRET"


def repair_mode_enabled() -> bool:
    return os.environ.get(REPAIR_ENV_FLAG, "").strip() in ("1", "true", "yes", "on")


def ensure_auth_loaded() -> dict:
    """Load key into process env using precedence; return safe source metadata."""
    resolved = resolve_auth_source(include_desktop=True)
    if resolved.get("_value"):
        os.environ["OPENROUTER_API_KEY"] = resolved["_value"]
    return {k: v for k, v in resolved.items() if k != "_value"}


def get_api_key_for_request() -> tuple[str | None, dict]:
    ensure_auth_loaded()
    cfg = DoofusConfig.from_env()
    key = cfg.openrouter_api_key
    source = resolve_auth_source(include_desktop=False)
    if key:
        if not source.get("secret_found"):
            source = resolve_auth_source(include_desktop=True)
        return key, {k: v for k, v in source.items() if k != "_value"}
    resolved = resolve_auth_source(include_desktop=True)
    return resolved.get("_value"), {k: v for k, v in resolved.items() if k != "_value"}


def openrouter_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://127.0.0.1:8765",
        "X-Title": "Doofus Local Dashboard",
    }
