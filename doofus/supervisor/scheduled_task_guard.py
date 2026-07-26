"""Scheduled task state guard — process-based inference; schtasks optional (hangs on some hosts)."""
from __future__ import annotations

import json
import os
import subprocess

from doofus.core.doofus_paths import STATE
from doofus.supervisor.process_singleton import read_singleton_pid, _pid_alive

REGISTRATION_FILE = STATE / "runtime_tasks_registration.json"
USE_SCHTASKS = os.environ.get("DOOFUS_USE_SCHTASKS", "").lower() in ("1", "true", "yes")


def _load_registration() -> dict:
    if not REGISTRATION_FILE.exists():
        return {}
    try:
        return json.loads(REGISTRATION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _process_state(role: str) -> str:
    pid = read_singleton_pid(role)
    if pid and _pid_alive(pid):
        return "Running"
    if read_singleton_pid(role) is not None:
        return "Ready"
    return "unknown"


def _task_state(name: str) -> str:
    if not USE_SCHTASKS:
        return "unknown"
    try:
        proc = subprocess.run(
            ["schtasks", "/Query", "/TN", name, "/FO", "LIST"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if proc.returncode != 0:
            return "unknown"
        for line in (proc.stdout or "").splitlines():
            if line.strip().startswith("Status:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "unknown"


def get_scheduled_task_states() -> dict:
    reg = _load_registration()
    sup = _process_state("doofus_supervisor")
    dash = _process_state("doofus_dashboard")
    runtime_mgr = _process_state("doofus_runtime_manager")
    watch = runtime_mgr if runtime_mgr == "Running" else "unknown"
    dash_watch = dash if dash == "Running" else "unknown"

    if USE_SCHTASKS:
        sup = _task_state("Doofus-24-7-Supervisor") if sup == "unknown" else sup
        dash = _task_state("Doofus-Local-Dashboard") if dash == "unknown" else dash
        watch = _task_state("Doofus-24-7-Watchdog")
        dash_watch = _task_state("Doofus-Dashboard-Watchdog")
        runtime_mgr = _task_state("Doofus-Runtime-Manager") if runtime_mgr == "unknown" else runtime_mgr

    registered = bool(reg.get("registered_at"))
    mgr_active = runtime_mgr == "Running"
    return {
        "supervisor_state": sup,
        "dashboard_state": dash,
        "watchdog_state": watch,
        "dashboard_watchdog_state": dash_watch,
        "runtime_manager_state": runtime_mgr,
        "supervisor_running": sup == "Running",
        "dashboard_running": dash == "Running",
        "watchdog_registered": registered or watch != "unknown" or mgr_active,
        "dashboard_watchdog_registered": registered or dash_watch != "unknown",
        "runtime_manager_registered": registered or runtime_mgr != "unknown",
        "runtime_manager_running": mgr_active,
        "inference_mode": "schtasks" if USE_SCHTASKS else "process_lock",
    }


def record_task_registration(tasks: list[str]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone

    REGISTRATION_FILE.write_text(
        json.dumps(
            {"registered_at": datetime.now(timezone.utc).isoformat(), "tasks": tasks},
            indent=2,
        ),
        encoding="utf-8",
    )


def restart_task(name: str) -> bool:
    if not USE_SCHTASKS:
        return False
    try:
        subprocess.run(["schtasks", "/End", "/TN", name], capture_output=True, timeout=2)
        proc = subprocess.run(["schtasks", "/Run", "/TN", name], capture_output=True, timeout=3)
        return proc.returncode == 0
    except Exception:
        return False
