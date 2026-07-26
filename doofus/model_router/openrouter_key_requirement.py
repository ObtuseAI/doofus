"""OpenRouter key shape requirements."""
from __future__ import annotations

from doofus.model_router.provider_identity import OPENROUTER_SHAPE
from doofus.model_router.unified_secret_resolver import resolve_unified_secret


def check_openrouter_key_requirement() -> dict:
    secret = resolve_unified_secret()
    shape = secret.get("key_shape", "unknown")
    ok = shape == OPENROUTER_SHAPE and secret.get("secret_found")
    return {
        "requirement_met": ok,
        "key_shape": shape,
        "expected_shape": OPENROUTER_SHAPE,
        "secret_found": secret.get("secret_found", False),
        "secret_value": "REDACTED",
        "message": "OpenRouter DeepSeek lane ready" if ok else "OpenRouter lane requires openrouter_like key",
    }
