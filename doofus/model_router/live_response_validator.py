"""Validate live model JSON responses."""
from __future__ import annotations

import json
import re

_SAFE_FIELDS = frozenset({
    "candidate_name", "mutation_trait", "expected_metric", "safety_note", "validation_plan",
})


def extract_json_object(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def validate_live_proposal(data: dict | None) -> dict:
    if not data:
        return {"valid": False, "reason": "no_json_object"}
    keys = set(data.keys())
    if not keys & _SAFE_FIELDS:
        return {"valid": False, "reason": "missing_expected_fields"}
    for k, v in data.items():
        if isinstance(v, str) and ("sk-" in v or "OPENROUTER" in v.upper()):
            return {"valid": False, "reason": "secret_like_content"}
    return {"valid": True, "fields": sorted(keys & _SAFE_FIELDS)}
