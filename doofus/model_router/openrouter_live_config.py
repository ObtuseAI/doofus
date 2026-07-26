"""OpenRouter DeepSeek live provider configuration and validation."""
from __future__ import annotations

import os
from typing import Any

from doofus.core.doofus_env_loader import load_doofus_env
from doofus.safety.secret_guard import assert_no_secret_in_payload

DEEPSEEK_V4_FLASH_ALIAS = "deepseekv4flash"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_LIVE_PROVIDER = "openrouter"
DEFAULT_MAX_MODEL_CALLS = 2
DEFAULT_MAX_COST_USD = 0.05
DEFAULT_TIMEOUT_SECONDS = 120


def openrouter_base_url() -> str:
    load_doofus_env()
    return os.environ.get("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL).strip().rstrip("/")


def resolve_model_alias() -> str:
    load_doofus_env()
    return os.environ.get("DOOFUS_OPENROUTER_MODEL_ALIAS", DEEPSEEK_V4_FLASH_ALIAS).strip().lower()


def resolve_concrete_model_id(*, require_explicit: bool = False) -> tuple[str | None, str | None]:
    """Return (model_id, error_reason)."""
    load_doofus_env()
    model_id = os.environ.get("DOOFUS_OPENROUTER_MODEL_ID", "").strip()
    if not model_id:
        model_id = os.environ.get("DOOFUS_MODEL_NAME", "").strip()
    alias = resolve_model_alias()
    if alias == DEEPSEEK_V4_FLASH_ALIAS and not model_id:
        if require_explicit:
            return None, "DOOFUS_OPENROUTER_MODEL_ID required for deepseekv4flash live route"
        return None, "model_id_missing"
    if not model_id:
        return None, "DOOFUS_OPENROUTER_MODEL_ID or DOOFUS_MODEL_NAME required"
    return model_id, None


def resolve_api_key_present() -> bool:
    load_doofus_env()
    for key in ("OPENROUTER_API_KEY", "DOOFUS_OPENROUTER_API_KEY"):
        if os.environ.get(key, "").strip():
            return True
    return False


def fallbacks_disabled() -> bool:
    load_doofus_env()
    return os.environ.get("DOOFUS_PROVIDER_FALLBACKS_DISABLED", "1") == "1"


def live_provider_name() -> str:
    load_doofus_env()
    live = os.environ.get("DOOFUS_LIVE_PROVIDER", "").strip().lower()
    if live:
        return live
    mp = os.environ.get("DOOFUS_MODEL_PROVIDER", "").strip().lower()
    if mp == "openrouter":
        return "openrouter"
    return ""


def apply_openrouter_live_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Apply OpenRouter-primary live env without mutating secrets."""
    load_doofus_env()
    target = dict(env or os.environ)
    target["DOOFUS_MODEL_PROVIDER"] = "openrouter"
    target["DOOFUS_LIVE_PROVIDER"] = "openrouter"
    target["DOOFUS_OPENROUTER_MODEL_ALIAS"] = resolve_model_alias()
    target["DOOFUS_PROVIDER_FALLBACKS_DISABLED"] = "1"
    target["DOOFUS_PREFER_CURSOR"] = "0"
    target["DOOFUS_CURSOR_HYBRID_FALLBACK"] = "0"
    model_id, _ = resolve_concrete_model_id()
    if model_id:
        target["DOOFUS_MODEL_NAME"] = model_id
    return target


def validate_openrouter_live_config(*, dry_run: bool = False, require_model_id: bool = False) -> dict[str, Any]:
    load_doofus_env()
    alias = resolve_model_alias()
    model_id, model_err = resolve_concrete_model_id(require_explicit=require_model_id and not dry_run)
    key_present = resolve_api_key_present()
    timeout = int(os.environ.get("DOOFUS_MODEL_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    max_calls = int(os.environ.get("DOOFUS_LIVE_MAX_MODEL_CALLS", str(DEFAULT_MAX_MODEL_CALLS)))
    max_cost = float(os.environ.get("DOOFUS_LIVE_MAX_COST_USD", str(DEFAULT_MAX_COST_USD)))

    blockers: list[str] = []
    if not dry_run and not key_present:
        blockers.append("OPENROUTER_API_KEY missing")
    if model_err and (require_model_id or not dry_run):
        blockers.append(model_err)
    if live_provider_name() not in ("openrouter", ""):
        blockers.append(f"DOOFUS_LIVE_PROVIDER must be openrouter, got {live_provider_name()}")

    ready = not blockers
    payload = {
        "classification": "DOOFUS_OPENROUTER_LIVE_CONFIG_READY" if ready else "DOOFUS_OPENROUTER_LIVE_CONFIG_BLOCKED",
        "provider": "openrouter",
        "model_alias": alias,
        "concrete_model_id": model_id,
        "model_id_configured": bool(model_id),
        "api_key_present": key_present,
        "openrouter_base_url": openrouter_base_url(),
        "fallbacks_disabled": fallbacks_disabled(),
        "cursor_fallback": "disabled" if fallbacks_disabled() else "configurable",
        "timeout_seconds": timeout,
        "max_model_calls": max_calls,
        "max_cost_usd": max_cost,
        "blockers": blockers,
        "ready": ready,
    }
    return assert_no_secret_in_payload(payload)
