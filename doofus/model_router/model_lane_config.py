"""Model lane configuration per provider."""
from __future__ import annotations

import os

from doofus.model_router.provider_capability_matrix import capabilities


def openai_model_name() -> str | None:
    return os.environ.get("DOOFUS_OPENAI_MODEL", "").strip() or None


def openrouter_model_name() -> str:
    from doofus.model_router.openrouter_live_config import resolve_concrete_model_id

    model_id, _ = resolve_concrete_model_id()
    if model_id:
        return model_id
    return os.environ.get("DOOFUS_MODEL_NAME", capabilities("openrouter")["default_model"]).strip()


def cursor_model_name() -> str:
    from doofus.config.cursor_composer_config import cursor_model_id
    return os.environ.get("DOOFUS_CURSOR_MODEL", cursor_model_id()).strip()


def model_for_provider(provider: str) -> tuple[str | None, str | None]:
    """Return (model_name, error_reason). error_reason set if model_missing."""
    if provider == "cursor":
        return cursor_model_name(), None
    if provider == "openai":
        model = openai_model_name() or capabilities("openai")["default_model"]
        if not model:
            return None, "model_missing"
        return model, None
    if provider == "openrouter":
        return openrouter_model_name(), None
    if provider == "dry_run":
        return "dry_run", None
    return None, "provider_blocked"
