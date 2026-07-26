"""Parse OpenRouter secrets from files — never expose values."""
from __future__ import annotations

import json
from pathlib import Path

from doofus.model_router.secret_source_validator import validate_secret_value

ENV_KEY_NAMES = ("OPENROUTER_API_KEY", "DOOFUS_OPENROUTER_API_KEY")
JSON_KEY_NAMES = ("OPENROUTER_API_KEY", "openrouter_api_key", "DOOFUS_OPENROUTER_API_KEY")


def _strip_inline_comment(line: str) -> str:
    if line.lstrip().startswith("#"):
        return ""
    for sep in (" #", "\t#"):
        if sep in line:
            line = line.split(sep, 1)[0]
    return line.strip()


def parse_secret_text(text: str) -> str | None:
    """Extract first plausible API key from file text."""
    text = text.strip()
    if not text:
        return None

    # JSON object
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for name in JSON_KEY_NAMES:
                    v = data.get(name)
                    if isinstance(v, str) and v.strip():
                        return v.strip().strip('"').strip("'")
        except json.JSONDecodeError:
            pass

    for raw_line in text.splitlines():
        line = _strip_inline_comment(raw_line.strip())
        if not line or line.startswith("#"):
            continue
        for name in ENV_KEY_NAMES:
            prefix = f"{name}="
            if line.upper().startswith(prefix.upper()):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
        # raw key line (skip human labels)
        low = line.lower()
        if low.startswith("api key") or low.startswith("openrouter"):
            continue
        if line.startswith("sk-"):
            return line.strip().strip('"').strip("'")
    return None


def read_secret_file(path: Path) -> dict:
    if not path.exists() or not path.is_file():
        return {
            "secret_found": False,
            "secret_source_type": "missing",
            "secret_source_path": str(path),
            "secret_length_bucket": "unknown",
            "key_shape": "unknown",
            "secret_value": "REDACTED",
        }
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {
            "secret_found": False,
            "secret_source_type": "desktop_file",
            "secret_source_path": str(path),
            "secret_length_bucket": "unknown",
            "key_shape": "unknown",
            "secret_value": "REDACTED",
        }
    value = parse_secret_text(text)
    meta = validate_secret_value(value)
    meta["secret_source_type"] = "desktop_file"
    meta["secret_source_path"] = str(path)
    if value:
        meta["_value"] = value  # internal only — never serialize
    return meta
