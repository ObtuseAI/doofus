"""Low-level OpenRouter provider probe — status codes only."""
from __future__ import annotations

import requests

from doofus.model_router.openrouter_auth_config import OPENROUTER_CHAT_URL, openrouter_headers
from doofus.model_router.model_secret_redactor import redact_secrets

DEFAULT_MODEL = "deepseek/deepseek-v4-flash"


def probe_chat(api_key: str, *, max_tokens: int = 8) -> dict:
    headers = openrouter_headers(api_key)
    body = {
        "model": DEFAULT_MODEL,
        "messages": [{"role": "user", "content": "Reply with OK only."}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    try:
        r = requests.post(OPENROUTER_CHAT_URL, headers=headers, json=body, timeout=45)
        status = r.status_code
        err_class = "none"
        if status >= 400:
            try:
                msg = r.json().get("error", {}).get("message", r.text[:80])
            except Exception:
                msg = r.text[:80]
            msg = redact_secrets(str(msg))
            if status == 401:
                err_class = "unauthorized"
            elif status == 403:
                err_class = "forbidden"
            elif status == 429:
                err_class = "rate_limited"
            else:
                err_class = "provider_error"
            return {"ok": False, "status_code": status, "error_class": err_class, "error_message": msg[:120]}
        return {"ok": True, "status_code": status, "error_class": "none", "error_message": ""}
    except requests.RequestException as exc:
        safe = redact_secrets(str(exc))
        return {"ok": False, "status_code": 0, "error_class": "network_error", "error_message": safe[:120]}
