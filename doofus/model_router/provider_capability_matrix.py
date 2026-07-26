"""Provider capability matrix."""
from __future__ import annotations

CAPABILITIES = {
    "openrouter": {
        "deepseek_lane": True,
        "live_mutations": True,
        "env_keys": ("OPENROUTER_API_KEY", "DOOFUS_OPENROUTER_API_KEY"),
        "default_model": "deepseek/deepseek-v4-flash",
    },
    "openai": {
        "deepseek_lane": False,
        "live_mutations": True,
        "env_keys": ("OPENAI_API_KEY", "DOOFUS_OPENAI_API_KEY"),
        "default_model": "gpt-4o-mini",
    },
    "dry_run": {"deepseek_lane": False, "live_mutations": False, "env_keys": (), "default_model": "dry_run"},
    "cursor": {
        "deepseek_lane": False,
        "live_mutations": True,
        "env_keys": ("CURSOR_API_KEY",),
        "default_model": "composer-2.5",
    },
    "blocked": {"deepseek_lane": False, "live_mutations": False, "env_keys": (), "default_model": ""},
}


def capabilities(provider: str) -> dict:
    return dict(CAPABILITIES.get(provider, CAPABILITIES["blocked"]))
