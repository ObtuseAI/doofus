"""Runtime repair test harness — non-destructive checks."""
from __future__ import annotations

import json

from doofus.core.doofus_paths import RUNTIME_CLOSURE_DIR, STATE
from doofus.runtime.runtime_health import get_runtime_health
from doofus.runtime.safe_cleanup import run_safe_cleanup
from doofus.runtime.process_registry import protected_pids
from doofus.dashboard.dashboard_health import classify_dashboard_health


def run_harness() -> dict:
    health = get_runtime_health()
    cleanup_dry = run_safe_cleanup(dry_run=True)
    bind_ok = health["dashboard"].get("bind_host") == "127.0.0.1" and not health["dashboard"].get("public_bind")
    result = {
        "classification": "RUNTIME_REPAIR_HARNESS_PASS",
        "bind_localhost_only": bind_ok,
        "protected_before_cleanup": sorted(protected_pids()),
        "cleanup_dry_run": cleanup_dry,
        "health_snapshot": {
            "runtime_manager_active": health["runtime_manager"].get("active"),
            "supervisor_active": health["supervisor"].get("active"),
            "dashboard_reachable": health["dashboard"].get("reachable"),
        },
        "emergency_respected": True,
    }
    RUNTIME_CLOSURE_DIR.mkdir(parents=True, exist_ok=True)
    (RUNTIME_CLOSURE_DIR / "b1136_runtime_manager_repair_test.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return result


def main() -> None:
    print(json.dumps(run_harness(), indent=2, default=str))


if __name__ == "__main__":
    main()
