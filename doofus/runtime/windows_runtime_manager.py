"""Windows runtime manager — persistent supervisor/dashboard/watchdog repair loop."""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone

from doofus.core.doofus_paths import STATE
from doofus.runtime.process_registry import register_role
from doofus.runtime.runtime_health import get_runtime_health
from doofus.runtime.runtime_repair import repair_all
from doofus.supervisor.process_singleton import acquire_singleton, release_singleton
from doofus.supervisor.doofus_heartbeat import emit_heartbeat

CHECK_SECONDS = int(os.environ.get("DOOFUS_RUNTIME_MANAGER_INTERVAL", "60"))
STATE_FILE = STATE / "runtime_manager_state.json"


def _write_state(active: bool, *, detail: dict | None = None) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(
            {"active": active, "updated_at": datetime.now(timezone.utc).isoformat(), "detail": detail or {}},
            indent=2,
        ),
        encoding="utf-8",
    )


def run_once() -> dict:
    register_role("doofus_runtime_manager")
    result = repair_all()
    health = get_runtime_health()
    emit_heartbeat("runtime_manager_tick", {"health": {"supervisor": health["supervisor"], "dashboard": health["dashboard"]}})
    out = {"classification": "RUNTIME_MANAGER_TICK", "repair": result, "health": health}
    _write_state(True, detail={"last_repair": result})
    (STATE / "runtime_manager_last.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return out


def serve() -> int:
    if not acquire_singleton("doofus_runtime_manager"):
        print(json.dumps({"classification": "RUNTIME_MANAGER_DUPLICATE"}))
        return 0
    register_role("doofus_runtime_manager")
    _write_state(True)
    emit_heartbeat("runtime_manager_start", {})
    try:
        while True:
            try:
                out = run_once()
                print(json.dumps({"classification": out["classification"], "supervisor_active": out["health"]["supervisor"].get("active")}))
            except Exception as exc:
                _write_state(True, detail={"last_error": type(exc).__name__})
                print(json.dumps({"classification": "RUNTIME_MANAGER_ERROR", "error": type(exc).__name__}))
            time.sleep(CHECK_SECONDS)
    finally:
        _write_state(False)
        release_singleton("doofus_runtime_manager")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--serve", action="store_true")
    p.add_argument("--once", action="store_true")
    args = p.parse_args()
    if args.serve:
        return serve()
    out = run_once()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
