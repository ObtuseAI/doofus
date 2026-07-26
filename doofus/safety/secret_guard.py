"""Secret guard — never log or persist keys."""
from __future__ import annotations
import os
import re

SECRET_ENV = ("OPENROUTER_API_KEY", "API_KEY", "SECRET")
KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{20,}")

def key_present(name: str = "OPENROUTER_API_KEY") -> bool:
    from doofus.core.doofus_env_loader import load_doofus_env
    load_doofus_env()
    return bool(os.environ.get(name, "").strip())

def redact_text(text: str) -> str:
    from doofus.model_router.model_secret_redactor import redact_secrets
    return redact_secrets(text)

_REDACT_KEYS = frozenset({
    "OPENROUTER_API_KEY", "API_KEY", "SECRET", "PASSWORD", "TOKEN",
    "OPENROUTER_API_KEY_VALUE",
})

def assert_no_secret_in_payload(payload: dict) -> dict:
    safe = {}
    for k, v in payload.items():
        ku = k.upper()
        if ku in _REDACT_KEYS or ku.endswith("_KEY") or ku.endswith("_SECRET") or ku.endswith("_PASSWORD"):
            safe[k] = "REDACTED"
        elif isinstance(v, str):
            safe[k] = redact_text(v)
        else:
            safe[k] = v
    return safe
