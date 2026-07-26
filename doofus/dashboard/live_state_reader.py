"""Read runtime JSON state for dashboard."""
from __future__ import annotations
import json
from doofus.core.doofus_paths import STATE, CONTROL, RUN_ENABLED, STOP_REQUEST, EMERGENCY_STOP
from doofus.supervisor.doofus_crash_recovery import load_checkpoint
from doofus.supervisor.doofus_cycle_checkpoint import read_checkpoint
from doofus.safety.on_off_switch import status as switch_status

def read_control_state() -> dict:
    return switch_status()

def read_checkpoint_status() -> dict:
    cp = read_checkpoint()
    legacy = load_checkpoint()
    return {"cycle_checkpoint": cp, "legacy_checkpoint": legacy}

def read_latest_error() -> str:
    cp = read_checkpoint()
    err = cp.get("data", {}).get("last_error", "")
    if err:
        return str(err)[:500]
    data = cp.get("data", {})
    mr = data.get("classification") or data.get("model_result", {})
    if isinstance(mr, dict):
        e = mr.get("error", "")
        if e:
            from doofus.model_router.model_secret_redactor import redact_secrets
            return redact_secrets(str(e))[:500]
    return ""
