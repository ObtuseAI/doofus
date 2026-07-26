# -*- coding: utf-8 -*-
"""Cursor Composer 2.5 amplification profile for Doofus."""
from __future__ import annotations

import os

DEFAULTS: dict[str, str] = {
    "DOOFUS_MODEL_PROVIDER": "cursor",
    "DOOFUS_PREFER_CURSOR": "1",
    "DOOFUS_CURSOR_MODEL": "composer-2.5",
    "DOOFUS_CURSOR_MUTATION_BATCH": "8",
    "DOOFUS_CURSOR_TIMEOUT_SECONDS": "120",
    "DOOFUS_CURSOR_HYBRID_FALLBACK": "1",
    "DOOFUS_CURSOR_USE_AGENT_CLI": "1",
    "DOOFUS_CURSOR_PREFER_AGENT_CLI": "1",
    "DOOFUS_MODEL_GUIDED_WEIGHT": "2.5",
    "DOOFUS_BASE_CANDIDATES_PER_CYCLE": "20",
    "DOOFUS_MAX_CANDIDATES_PER_CYCLE": "56",
    "DOOFUS_MAX_MODEL_CALLS_PER_HOUR": "180",
    "DOOFUS_MAX_DAILY_COST_USD": "25",
    "DOOFUS_AGGRESSIVE_EVOLUTION_MODE": "1",
}


def apply_defaults(*, force: bool = False) -> dict[str, str]:
    applied: dict[str, str] = {}
    for key, value in DEFAULTS.items():
        if force or key not in os.environ:
            os.environ[key] = value
            applied[key] = value
    return applied


def cursor_composer_enabled() -> bool:
    return os.environ.get("DOOFUS_MODEL_PROVIDER", "").strip().lower() == "cursor"


def cursor_model_id() -> str:
    return os.environ.get("DOOFUS_CURSOR_MODEL", "composer-2.5")


def cursor_mutation_batch() -> int:
    return int(os.environ.get("DOOFUS_CURSOR_MUTATION_BATCH", "8"))


def runtime_snapshot() -> dict:
    return {
        **{k: os.environ.get(k, DEFAULTS.get(k)) for k in DEFAULTS},
        "cursor_api_key_present": bool(os.environ.get("CURSOR_API_KEY", "").strip()),
    }
