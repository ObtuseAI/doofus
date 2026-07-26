"""Probe for live cycle readiness."""
from __future__ import annotations
from doofus.model_router.model_environment_probe import probe_model_environment

def probe_live_cycle_ready() -> dict:
    e = probe_model_environment()
    return {"ready": e["model_mode"] == "live" and e["openrouter_api_key_present"], "environment": e}
