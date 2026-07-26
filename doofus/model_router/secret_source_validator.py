"""Validate secret metadata without exposing values."""
from __future__ import annotations

import re

_KEY_LIKE = re.compile(r"^sk-[A-Za-z0-9_\-\.]+$")


def length_bucket(length: int) -> str:
    if length <= 0:
        return "unknown"
    if length < 40:
        return "short"
    if length <= 120:
        return "normal"
    return "long"


def classify_key_shape(value: str) -> str:
    """Classify key shape without emitting prefix/suffix."""
    if not value or not value.strip():
        return "unknown"
    v = value.strip()
    if v.startswith("sk-or-v1-"):
        return "openrouter_like"
    if v.startswith("sk-proj-"):
        return "openai_like"
    if _KEY_LIKE.match(v):
        return "unknown"
    return "unknown"


def validate_secret_value(value: str | None) -> dict:
    val = (value or "").strip().strip('"').strip("'")
    found = bool(val)
    return {
        "secret_found": found,
        "secret_length_bucket": length_bucket(len(val)),
        "key_shape": classify_key_shape(val) if found else "unknown",
        "secret_value": "REDACTED",
    }
