"""Full functionality dashboard panel."""
from __future__ import annotations

from doofus.core.doofus_paths import RUNTIME_CLOSURE_DIR
from doofus.runtime.runtime_health import get_runtime_health
import json


def get_full_functionality_panel() -> dict:
    verdict = {}
    p = RUNTIME_CLOSURE_DIR / "b1138_final_functionality_verdict.json"
    if p.exists():
        verdict = json.loads(p.read_text(encoding="utf-8"))
    health = get_runtime_health()
    return {
        "verdict": verdict.get("verdict", "pending"),
        "checks": verdict.get("checks", {}),
        "supervisor_active": health["supervisor"].get("active"),
        "dashboard_reachable": health["dashboard"].get("reachable"),
        "runtime_manager_active": health["runtime_manager"].get("active"),
        "watchdog_active": health["watchdog"].get("active"),
        "heartbeat_age_seconds": health["supervisor"].get("heartbeat_age_seconds"),
    }
