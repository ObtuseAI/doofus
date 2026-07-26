"""Provider identity from key shape — no secret exposure."""
from __future__ import annotations

from doofus.model_router.secret_source_validator import classify_key_shape

OPENROUTER_SHAPE = "openrouter_like"
OPENAI_SHAPE = "openai_like"


def provider_for_key_shape(key_shape: str) -> str:
    if key_shape == OPENROUTER_SHAPE:
        return "openrouter"
    if key_shape == OPENAI_SHAPE:
        return "openai"
    return "blocked"


def compatible_provider(explicit: str, key_shape: str) -> bool:
    if explicit in ("dry_run", "blocked", "cursor"):
        return True
    if explicit == "openrouter" and key_shape != OPENROUTER_SHAPE:
        return False
    if explicit == "openai" and key_shape != OPENAI_SHAPE:
        return False
    return True
