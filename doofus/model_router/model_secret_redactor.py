"""Redact secrets from strings."""
from __future__ import annotations
import re

_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"OPENROUTER_API_KEY\s*=\s*\S+", re.I),
)

def redact_secrets(text: str) -> str:
    out = text
    for p in _PATTERNS:
        out = p.sub("REDACTED", out)
    return out
