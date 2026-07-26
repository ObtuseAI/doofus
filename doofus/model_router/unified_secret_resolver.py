"""Unified secret resolution for any provider lane."""
from __future__ import annotations

import os
from pathlib import Path

from doofus.core.doofus_paths import ROOT
from doofus.model_router.desktop_secret_loader import get_desktop_secret_value, load_desktop_secret
from doofus.model_router.secret_source_validator import validate_secret_value

GITIGNORED_ENV = ROOT / ".env"
_KEY_ENV_NAMES = (
    "OPENROUTER_API_KEY",
    "DOOFUS_OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "DOOFUS_OPENAI_API_KEY",
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


def _read_gitignored_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not GITIGNORED_ENV.exists():
        return out
    for raw in GITIGNORED_ENV.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        name = k.strip().lstrip("\ufeff")
        if name in _KEY_ENV_NAMES:
            val = v.strip().strip('"').strip("'")
            if val:
                out[name] = val
    return out


def resolve_unified_secret() -> dict:
    """Find first available secret from env or desktop."""
    if os.environ.get("DOOFUS_DISABLE_SECRET_DISCOVERY", "").strip() == "1":
        return {
            "secret_found": False,
            "secret_source": "disabled",
            "secret_source_path": "",
            "key_shape": "unknown",
            "secret_length_bucket": "unknown",
            "secret_value": "REDACTED",
        }
    for name in _KEY_ENV_NAMES:
        val = os.environ.get(name, "").strip()
        if val:
            meta = validate_secret_value(val)
            return {
                "secret_found": True,
                "secret_source": "process_env",
                "secret_source_path": f"process:{name}",
                "key_shape": meta["key_shape"],
                "secret_length_bucket": meta["secret_length_bucket"],
                "secret_value": "REDACTED",
                "_value": val,
                "_env_name": name,
            }
    for name in _KEY_ENV_NAMES:
        val = _read_user_env(name)
        if val:
            meta = validate_secret_value(val)
            return {
                "secret_found": True,
                "secret_source": "user_env",
                "secret_source_path": f"user:{name}",
                "key_shape": meta["key_shape"],
                "secret_length_bucket": meta["secret_length_bucket"],
                "secret_value": "REDACTED",
                "_value": val,
                "_env_name": name,
            }
    desk = get_desktop_secret_value()
    if desk:
        meta = validate_secret_value(desk)
        dm = load_desktop_secret()
        return {
            "secret_found": True,
            "secret_source": "desktop_file",
            "secret_source_path": dm.get("secret_source_path", "desktop"),
            "key_shape": meta["key_shape"],
            "secret_length_bucket": meta["secret_length_bucket"],
            "secret_value": "REDACTED",
            "_value": desk,
            "_env_name": "desktop",
        }
    for name, val in _read_gitignored_env().items():
        meta = validate_secret_value(val)
        return {
            "secret_found": True,
            "secret_source": "gitignored_env",
            "secret_source_path": str(GITIGNORED_ENV),
            "key_shape": meta["key_shape"],
            "secret_length_bucket": meta["secret_length_bucket"],
            "secret_value": "REDACTED",
            "_value": val,
            "_env_name": name,
        }
    return {
        "secret_found": False,
        "secret_source": "missing",
        "secret_source_path": "",
        "key_shape": "unknown",
        "secret_length_bucket": "unknown",
        "secret_value": "REDACTED",
    }


def apply_secret_to_provider_env(secret: dict, provider: str) -> None:
    val = secret.get("_value")
    if not val:
        return
    if provider == "openai":
        os.environ["OPENAI_API_KEY"] = val
        os.environ["DOOFUS_MODEL_PROVIDER"] = "openai"
    elif provider == "openrouter":
        os.environ["OPENROUTER_API_KEY"] = val
        os.environ["DOOFUS_MODEL_PROVIDER"] = "openrouter"
