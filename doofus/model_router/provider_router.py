"""Provider-aware model routing for Doofus."""
from __future__ import annotations

import json
import os

from doofus.core.doofus_env_loader import load_doofus_env
from doofus.model_router.model_lane_config import model_for_provider
from doofus.model_router.openrouter_live_config import fallbacks_disabled, live_provider_name, validate_openrouter_live_config
from doofus.model_router.provider_capability_matrix import capabilities
from doofus.model_router.provider_identity import compatible_provider, provider_for_key_shape
from doofus.model_router.unified_secret_resolver import apply_secret_to_provider_env, resolve_unified_secret
from doofus.safety.secret_guard import assert_no_secret_in_payload


def resolve_provider(*, diagnostic_openrouter: bool = False) -> dict:
    load_doofus_env()
    explicit = os.environ.get("DOOFUS_MODEL_PROVIDER", "").strip().lower()
    live_provider = live_provider_name()
    cursor_key = os.environ.get("CURSOR_API_KEY", "").strip()
    prefer_cursor = os.environ.get("DOOFUS_PREFER_CURSOR", "0") == "1" and not fallbacks_disabled()

    explicit_cursor_request = explicit == "cursor" and live_provider != "openrouter"
    openrouter_primary = live_provider == "openrouter" or explicit == "openrouter"
    if openrouter_primary and not explicit_cursor_request:
        cfg = validate_openrouter_live_config(dry_run=diagnostic_openrouter, require_model_id=not diagnostic_openrouter)
        secret = resolve_unified_secret()
        if cfg.get("ready") or diagnostic_openrouter:
            model, model_err = model_for_provider("openrouter")
            if model_err:
                return _result(
                    provider_selected="blocked",
                    provider_reason=model_err,
                    secret=secret,
                    model_name=None,
                    auth_status="model_missing",
                )
            key_shape = secret.get("key_shape", "openrouter_like") if secret.get("secret_found") else "openrouter_like"
            deepseek_ready = bool(cfg.get("ready"))
            return _result(
                provider_selected="openrouter" if deepseek_ready or diagnostic_openrouter else "dry_run",
                provider_reason="openrouter_primary_route",
                secret=secret if secret.get("secret_found") else {"secret_found": cfg.get("api_key_present"), "key_shape": key_shape, "secret_source": "openrouter_env"},
                model_name=model,
                auth_status="pending" if deepseek_ready else "no_key",
                live_provider_ready=deepseek_ready,
                deepseek_openrouter_ready=deepseek_ready,
            )
        if explicit == "openrouter" or live_provider == "openrouter":
            return _result(
                provider_selected="blocked",
                provider_reason=";".join(cfg.get("blockers") or ["openrouter_config_blocked"]),
                secret=resolve_unified_secret(),
                model_name=None,
                auth_status="blocked",
                safe_error_class="openrouter_config",
            )

    if explicit == "cursor" or (prefer_cursor and cursor_key and explicit in ("", "auto")):
        if cursor_key:
            model, model_err = model_for_provider("cursor")
            if model_err:
                return _result(
                    provider_selected="blocked",
                    provider_reason=model_err,
                    secret={"secret_found": True, "key_shape": "cursor", "secret_source": "cursor_api_key"},
                    model_name=None,
                    auth_status="model_missing",
                )
            return _result(
                provider_selected="cursor",
                provider_reason="cursor_api_key",
                secret={"secret_found": True, "key_shape": "cursor", "secret_source": "cursor_api_key"},
                model_name=model,
                auth_status="pending",
                live_provider_ready=True,
            )

    if explicit == "cursor" or (prefer_cursor and explicit in ("", "auto")):
        try:
            from doofus.model_router.cursor_agent_cli import agent_cli_available, probe_agent_auth

            if agent_cli_available() and probe_agent_auth().get("logged_in"):
                model, model_err = model_for_provider("cursor")
                if model_err:
                    return _result(
                        provider_selected="blocked",
                        provider_reason=model_err,
                        secret={"secret_found": True, "key_shape": "cursor", "secret_source": "agent_cli"},
                        model_name=None,
                        auth_status="model_missing",
                    )
                return _result(
                    provider_selected="cursor",
                    provider_reason="agent_cli_login",
                    secret={"secret_found": True, "key_shape": "cursor", "secret_source": "agent_cli"},
                    model_name=model,
                    auth_status="pending",
                    live_provider_ready=True,
                )
        except Exception:
            pass
        if explicit == "cursor":
            return _result(
                provider_selected="dry_run",
                provider_reason="cursor_auth_missing",
                secret={"secret_found": False, "key_shape": "cursor", "secret_source": "missing"},
                model_name="dry_run",
                auth_status="no_key",
            )

    secret = resolve_unified_secret()
    key_shape = secret.get("key_shape", "unknown")
    explicit = os.environ.get("DOOFUS_MODEL_PROVIDER", "").strip().lower()

    if not secret.get("secret_found"):
        return _result(
            provider_selected="dry_run",
            provider_reason="no_secret",
            secret=secret,
            model_name="dry_run",
            auth_status="no_key",
        )

    inferred = provider_for_key_shape(key_shape)
    if explicit == "cursor" and inferred in ("openai", "openrouter"):
        provider = inferred
    elif explicit and explicit not in ("", "auto"):
        if not compatible_provider(explicit, key_shape) and not diagnostic_openrouter:
            return _result(
                provider_selected="blocked",
                provider_reason="explicit_provider_incompatible_with_key_shape",
                secret=secret,
                model_name=None,
                auth_status="blocked",
                safe_error_class="provider_mismatch",
            )
        provider = explicit if explicit != "auto" else inferred
    else:
        provider = inferred

    if provider == "blocked" or key_shape == "unknown":
        return _result(
            provider_selected="dry_run",
            provider_reason="unknown_key_shape",
            secret=secret,
            model_name="dry_run",
            auth_status="unknown",
        )

    apply_secret_to_provider_env(secret, provider)
    model, model_err = model_for_provider(provider)
    if model_err:
        return _result(
            provider_selected="blocked",
            provider_reason=model_err,
            secret=secret,
            model_name=None,
            auth_status="model_missing",
            safe_error_class=model_err,
        )

    caps = capabilities(provider)
    deepseek_ready = provider == "openrouter" and key_shape == "openrouter_like"
    live_ready = provider in ("openai", "openrouter")

    return _result(
        provider_selected=provider,
        provider_reason="key_shape_inferred" if not explicit else "explicit_provider",
        secret=secret,
        model_name=model,
        auth_status="pending",
        live_provider_ready=live_ready,
        deepseek_openrouter_ready=deepseek_ready,
        fallback_used=explicit != provider if explicit else False,
    )


def _result(
    *,
    provider_selected: str,
    provider_reason: str,
    secret: dict,
    model_name: str | None,
    auth_status: str,
    live_provider_ready: bool = False,
    deepseek_openrouter_ready: bool = False,
    fallback_used: bool = False,
    safe_error_class: str = "none",
) -> dict:
    out = {
        "classification": "B1050_PROVIDER_ROUTER_READY",
        "provider_selected": provider_selected,
        "provider_reason": provider_reason,
        "key_shape": secret.get("key_shape", "unknown"),
        "secret_source": secret.get("secret_source", "missing"),
        "secret_source_path": secret.get("secret_source_path", ""),
        "model_name": model_name,
        "live_provider_ready": live_provider_ready,
        "deepseek_openrouter_ready": deepseek_openrouter_ready,
        "deepseek_lane_status": "ready" if deepseek_openrouter_ready else "auth_required",
        "fallback_used": fallback_used,
        "auth_status": auth_status,
        "safe_error_class": safe_error_class,
        "secret_value": "REDACTED",
    }
    return assert_no_secret_in_payload(out)


def safe_route_json() -> str:
    return json.dumps(resolve_provider(), indent=2)


def main() -> int:
    print(safe_route_json())
    r = resolve_provider()
    return 0 if r.get("provider_selected") not in ("blocked",) else 1


if __name__ == "__main__":
    raise SystemExit(main())
