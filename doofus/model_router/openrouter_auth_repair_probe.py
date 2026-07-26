"""OpenRouter auth repair probe — try env then Desktop once."""
from __future__ import annotations

import argparse
import json
import os

from doofus.model_router.auth_source_resolver import get_desktop_secret_value, resolve_auth_source
from doofus.model_router.openrouter_auth_config import ensure_auth_loaded, repair_mode_enabled
from doofus.model_router.openrouter_provider_probe import probe_chat
from doofus.safety.secret_guard import assert_no_secret_in_payload


def run_repair_probe() -> dict:
    from doofus.core.doofus_env_loader import load_doofus_env

    load_doofus_env()
    active = resolve_auth_source(include_desktop=False)
    active_val = active.get("_value")
    if not active_val:
        active = resolve_auth_source(include_desktop=True)
        active_val = active.get("_value")

    attempts: list[dict] = []
    winning = "none"
    provider_auth = "failing"

    if active_val:
        first = probe_chat(active_val)
        attempts.append({
            "source_name": active.get("source_name", "unknown"),
            "source_path": active.get("source_path", ""),
            **first,
        })
        if first.get("ok"):
            winning = active.get("source_name", "process_env")
            provider_auth = "ok"

    if provider_auth != "ok" and repair_mode_enabled():
        desk_val = get_desktop_secret_value()
        desk_meta = resolve_auth_source(include_desktop=True)
        if desk_val and (not active_val or desk_val != active_val):
            second = probe_chat(desk_val)
            attempts.append({
                "source_name": "desktop_secret",
                "source_path": desk_meta.get("source_path", "desktop"),
                **second,
            })
            if second.get("ok"):
                winning = "desktop_secret"
                provider_auth = "ok"
                os.environ["OPENROUTER_API_KEY"] = desk_val
        elif desk_val and active_val == desk_val and attempts and not attempts[0].get("ok"):
            # same value already tried — note shape mismatch possibility
            attempts.append({
                "source_name": "desktop_secret",
                "source_path": desk_meta.get("source_path", "desktop"),
                "status_code": attempts[0].get("status_code", 401),
                "error_class": attempts[0].get("error_class", "unauthorized"),
                "error_message": "desktop_same_as_active_source",
                "ok": False,
            })

    classification = "B1042_OPENROUTER_AUTH_REPAIR_PROBE_PASS" if provider_auth == "ok" else "B1042_OPENROUTER_AUTH_REPAIR_PROBE_AUTH_BLOCKED"
    if provider_auth != "ok" and not attempts:
        classification = "B1042_OPENROUTER_AUTH_REPAIR_PROBE_BLOCKED"

    desk = resolve_auth_source(include_desktop=True)
    return assert_no_secret_in_payload({
        "classification": classification,
        "provider_auth": provider_auth,
        "winning_source": winning,
        "repair_mode": repair_mode_enabled(),
        "active_env_source": active.get("source_name", "missing"),
        "desktop_secret_found": bool(desk.get("secret_found")),
        "desktop_key_shape": desk.get("key_shape", "unknown"),
        "desktop_length_bucket": desk.get("secret_length_bucket", "unknown"),
        "attempts": [{k: v for k, v in a.items() if k != "error_message" or len(str(v)) < 200} for a in attempts],
    })


def main() -> int:
    result = run_repair_probe()
    print(json.dumps(result, indent=2))
    return 0 if result.get("provider_auth") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
