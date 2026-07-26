"""Resolve OpenRouter API key source with safe precedence."""
from __future__ import annotations

import os
from pathlib import Path

from doofus.core.doofus_paths import ROOT
from doofus.model_router.desktop_secret_loader import get_desktop_secret_value, load_desktop_secret
from doofus.model_router.secret_source_validator import validate_secret_value

GITIGNORED_ENV = ROOT / ".env"

_SOURCE_ORDER = (
    ("process_env", "OPENROUTER_API_KEY"),
    ("process_env", "DOOFUS_OPENROUTER_API_KEY"),
    ("user_env", "OPENROUTER_API_KEY"),
    ("user_env", "DOOFUS_OPENROUTER_API_KEY"),
    ("desktop_secret", None),
    ("gitignored_env_file", None),
)


def _read_user_env(name: str) -> str | None:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            val, _ = winreg.QueryValueEx(key, name)
            if isinstance(val, str) and val.strip():
                return val.strip()
    except OSError:
        pass
    return None


def _read_gitignored_env() -> str | None:
    if not GITIGNORED_ENV.exists():
        return None
    text = GITIGNORED_ENV.read_text(encoding="utf-8-sig")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip().lstrip("\ufeff") in ("OPENROUTER_API_KEY", "DOOFUS_OPENROUTER_API_KEY"):
            val = v.strip().strip('"').strip("'")
            if val:
                return val
    return None


def resolve_auth_source(include_desktop: bool = True) -> dict:
    for source_type, env_name in _SOURCE_ORDER:
        if not include_desktop and source_type in ("desktop_secret", "gitignored_env_file"):
            continue
        value: str | None = None
        path = ""
        if source_type == "process_env" and env_name:
            value = os.environ.get(env_name, "").strip() or None
            path = f"process:{env_name}"
        elif source_type == "user_env" and env_name:
            value = _read_user_env(env_name)
            path = f"user:{env_name}"
        elif source_type == "desktop_secret" and include_desktop:
            meta = load_desktop_secret()
            value = meta.get("_value")
            path = meta.get("secret_source_path", "desktop")
        elif source_type == "gitignored_env_file":
            value = _read_gitignored_env()
            path = str(GITIGNORED_ENV)

        if value:
            meta = validate_secret_value(value)
            return {
                "source_name": source_type,
                "source_path": path,
                "secret_found": True,
                "secret_length_bucket": meta["secret_length_bucket"],
                "key_shape": meta["key_shape"],
                "secret_value": "REDACTED",
                "_value": value,
            }

    return {
        "source_name": "missing",
        "source_path": "",
        "secret_found": False,
        "secret_length_bucket": "unknown",
        "key_shape": "unknown",
        "secret_value": "REDACTED",
    }


def get_resolved_api_key(*, prefer_desktop: bool = False) -> tuple[str | None, dict]:
    if prefer_desktop:
        desk = get_desktop_secret_value()
        if desk:
            meta = validate_secret_value(desk)
            return desk, {
                "source_name": "desktop_secret",
                "source_path": load_desktop_secret().get("secret_source_path", "desktop"),
                **{k: meta[k] for k in ("secret_length_bucket", "key_shape")},
                "secret_value": "REDACTED",
            }
    resolved = resolve_auth_source(include_desktop=True)
    return resolved.get("_value"), {k: v for k, v in resolved.items() if k != "_value"}


def apply_to_process_env(source: dict | None = None) -> bool:
    resolved = source or resolve_auth_source(include_desktop=True)
    val = resolved.get("_value")
    if not val:
        return False
    os.environ["OPENROUTER_API_KEY"] = val
    return True
