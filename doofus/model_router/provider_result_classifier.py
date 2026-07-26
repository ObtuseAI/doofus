"""Classify provider operation results."""
from __future__ import annotations


def classify_live_result(provider: str, result: dict) -> str:
    cls = result.get("classification", "")
    if cls in ("DOOFUS_MODEL_LIVE", "DOOFUS_OPENAI_MODEL_LIVE"):
        if provider == "openai":
            return "DOOFUS_PROVIDER_LIVE_OPENAI"
        if provider == "openrouter":
            return "DOOFUS_PROVIDER_LIVE_OPENROUTER"
        return "DOOFUS_PROVIDER_LIVE"
    if "ERROR" in cls or "BLOCKED" in cls:
        return f"DOOFUS_PROVIDER_{provider.upper()}_BLOCKED"
    if cls == "DOOFUS_MODEL_DRY_RUN":
        return "DOOFUS_PROVIDER_DRY_RUN"
    return "DOOFUS_PROVIDER_UNKNOWN"


def classify_cycle(provider: str, live_ready: bool, deepseek_ready: bool, cycle: dict) -> str:
    cc = cycle.get("classification", "")
    if cc in ("B1003_LIVE_MODEL_CYCLE_PASS", "B1003_LIVE_MODEL_CYCLE_PASS_WITH_NOTES", "DOOFUS_CYCLE_COMPLETE"):
        if live_ready and provider == "openai" and not deepseek_ready:
            return "B1053_PROVIDER_AWARE_LIVE_CYCLE_PASS_WITH_NOTES"
        if live_ready and provider == "openrouter" and deepseek_ready:
            return "B1053_PROVIDER_AWARE_LIVE_CYCLE_PASS"
        return "B1053_PROVIDER_AWARE_LIVE_CYCLE_PASS_WITH_NOTES"
    if not live_ready:
        return "B1053_PROVIDER_AWARE_LIVE_CYCLE_AUTH_BLOCKED"
    return "B1053_PROVIDER_AWARE_LIVE_CYCLE_BLOCKED"
