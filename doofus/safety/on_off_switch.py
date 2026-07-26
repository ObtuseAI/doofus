"""Hard on/off control files."""
from __future__ import annotations

from doofus.core import doofus_paths
from doofus.core.doofus_events import utc_now

def ensure_control_dir() -> None:
    doofus_paths.CONTROL.mkdir(parents=True, exist_ok=True)

def status() -> dict:
    ensure_control_dir()
    return {
        "run_enabled": doofus_paths.RUN_ENABLED.exists(),
        "stop_requested": doofus_paths.STOP_REQUEST.exists(),
        "emergency_stop": doofus_paths.EMERGENCY_STOP.exists(),
        "may_run": (
            doofus_paths.RUN_ENABLED.exists()
            and not doofus_paths.STOP_REQUEST.exists()
            and not doofus_paths.EMERGENCY_STOP.exists()
        ),
        "checked_at": utc_now(),
    }

def start() -> dict:
    ensure_control_dir()
    doofus_paths.STOP_REQUEST.unlink(missing_ok=True)
    doofus_paths.EMERGENCY_STOP.unlink(missing_ok=True)
    doofus_paths.RUN_ENABLED.write_text(f"enabled_at={utc_now()}\n", encoding="utf-8")
    return status()

def stop() -> dict:
    ensure_control_dir()
    doofus_paths.STOP_REQUEST.write_text(f"stop_at={utc_now()}\n", encoding="utf-8")
    return status()

def emergency_stop() -> dict:
    ensure_control_dir()
    doofus_paths.EMERGENCY_STOP.write_text(f"emergency_at={utc_now()}\n", encoding="utf-8")
    return status()

def clear_emergency() -> None:
    doofus_paths.EMERGENCY_STOP.unlink(missing_ok=True)

def check_may_proceed() -> tuple[bool, str]:
    s = status()
    if s["emergency_stop"]:
        return False, "emergency_stop"
    if s["stop_requested"]:
        return False, "stop_requested"
    if not s["run_enabled"]:
        return False, "run_disabled"
    return True, "ok"


def check_may_prepare_one_cycle() -> tuple[bool, str]:
    """Preflight for operator-approved one-cycle launch while stop remains set."""
    s = status()
    if s["emergency_stop"]:
        return False, "emergency_stop"
    if not s["run_enabled"]:
        return False, "run_disabled"
    if not s["stop_requested"]:
        return False, "stop_not_requested_for_one_cycle"
    return True, "ok"
