"""Live cycle report snippet."""
from __future__ import annotations
from doofus.core.doofus_events import utc_now

def build_live_cycle_report(cycle: dict) -> dict:
    return {"classification": "DOOFUS_LIVE_CYCLE_REPORT", "cycle": cycle, "generated_at": utc_now()}
