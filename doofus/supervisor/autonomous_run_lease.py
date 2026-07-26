"""Autonomous runner session lease and external vs internal stop distinction."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doofus.core import doofus_paths

WORKSPACE = Path(__file__).resolve().parents[2]
SESSION_PATH = WORKSPACE / "runtime" / "state" / "autonomous_live_runner_session.json"
EXTERNAL_HALT_PATH = doofus_paths.CONTROL / "AUTONOMOUS_RUN_HALT.request"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stop_request_mtime() -> float:
    if doofus_paths.STOP_REQUEST.exists():
        return doofus_paths.STOP_REQUEST.stat().st_mtime
    return 0.0


def new_session_id() -> str:
    return f"autonomous_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"


def new_cycle_lease_id(session_id: str, cycle_index: int) -> str:
    return f"{session_id}_cycle_{cycle_index}"


def read_session() -> dict[str, Any]:
    if not SESSION_PATH.exists():
        return {}
    try:
        return json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_session(payload: dict[str, Any]) -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def start_session(*, session_id: str, max_cycles: int) -> dict[str, Any]:
    payload = {
        "runner_session_id": session_id,
        "started_at": utc_now(),
        "runner_state": "RUNNER_ACTIVE",
        "max_cycles": max_cycles,
        "cycles_completed": 0,
        "stop_mtime_at_session_start": stop_request_mtime(),
        "stop_mtime_after_internal_restore": stop_request_mtime(),
        "last_internal_stop_restore_at": None,
        "external_stop_requested_at": None,
        "stop_reason": None,
        "stop_observed_source": None,
    }
    write_session(payload)
    EXTERNAL_HALT_PATH.unlink(missing_ok=True)
    return payload


def update_session(**fields: Any) -> dict[str, Any]:
    session = read_session()
    session.update(fields)
    write_session(session)
    return session


def record_internal_stop_restore() -> dict[str, Any]:
    mtime = stop_request_mtime()
    return update_session(
        runner_state="CYCLE_COMPLETED_STOP_RESTORED",
        last_internal_stop_restore_at=utc_now(),
        stop_mtime_after_internal_restore=mtime,
        stop_reason="internal_guarded_one_cycle_restore",
        stop_observed_source="guarded_live_cycle_launch",
    )


def request_external_halt(*, reason: str = "operator_stop") -> dict[str, Any]:
    EXTERNAL_HALT_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXTERNAL_HALT_PATH.write_text(f"halt_at={utc_now()}\nreason={reason}\n", encoding="utf-8")
    return update_session(
        external_stop_requested_at=utc_now(),
        stop_reason=reason,
        stop_observed_source="external_operator",
        runner_state="HALTED_BY_OPERATOR_STOP",
    )


def external_stop_detected() -> tuple[bool, str]:
    from doofus.safety.on_off_switch import status

    switch = status()
    if switch.get("emergency_stop"):
        return True, "emergency_stop"
    if not switch.get("run_enabled"):
        return True, "run_disabled"
    if EXTERNAL_HALT_PATH.exists():
        return True, "autonomous_run_halt_request"
    session = read_session()
    recorded = session.get("stop_mtime_after_internal_restore")
    if recorded is not None:
        current = stop_request_mtime()
        if current > float(recorded) + 0.001:
            return True, "external_stop_request_mtime"
    if session.get("external_stop_requested_at"):
        return True, "external_stop_session_marker"
    return False, "ok"


def clear_session() -> None:
    SESSION_PATH.unlink(missing_ok=True)
    EXTERNAL_HALT_PATH.unlink(missing_ok=True)
