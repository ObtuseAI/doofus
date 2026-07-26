"""Runtime repair — restart dead/stale components only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

from doofus.core.doofus_paths import ROOT, STATE, VENV
from doofus.runtime.runtime_health import dashboard_health, supervisor_health
from doofus.runtime.heartbeat_contract import STALE_SECONDS
from doofus.safety.on_off_switch import status as switch_status
from doofus.supervisor.heartbeat_watchdog import heartbeat_age_seconds
from doofus.supervisor.process_singleton import read_singleton_pid, _pid_alive

REPAIR_LOG = STATE / "runtime_repair_log.json"
REPAIR_LOCK = STATE / "runtime_repair.lock"
PY = VENV / "Scripts" / "python.exe"
DETACHED_PROCESS = 0x00000008 if sys.platform == "win32" else 0


def _append_log(action: str, detail: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    rows = json.loads(REPAIR_LOG.read_text(encoding="utf-8")) if REPAIR_LOG.exists() else []
    rows.append({"at": datetime.now(timezone.utc).isoformat(), "action": action, **detail})
    REPAIR_LOG.write_text(json.dumps(rows[-100:], indent=2), encoding="utf-8")


_MODULE_ROLE = {
    "doofus.dashboard.doofus_dashboard_app": "doofus_dashboard",
    "doofus.supervisor.doofus_24_7_supervisor": "doofus_supervisor",
    "doofus.runtime.windows_runtime_manager": "doofus_runtime_manager",
}


def _repair_lock() -> bool:
    """Best-effort exclusive repair lock (non-blocking)."""
    STATE.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(REPAIR_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_repair_lock() -> None:
    try:
        REPAIR_LOCK.unlink(missing_ok=True)
    except Exception:
        pass


def _spawn(module: str) -> int | None:
    if not PY.exists():
        return None
    if sys.platform == "win32":
        subprocess.Popen(
            ["cmd", "/c", "start", "", "/B", str(PY), "-u", "-m", module],
            cwd=str(ROOT),
            env=os.environ.copy(),
        )
    else:
        subprocess.Popen(
            [str(PY), "-u", "-m", module],
            cwd=str(ROOT),
            env=os.environ.copy(),
            creationflags=DETACHED_PROCESS,
            close_fds=False,
        )
    import time
    from doofus.supervisor.process_singleton import read_singleton_pid

    role = _MODULE_ROLE.get(module)
    for _ in range(20):
        time.sleep(0.5)
        pid = read_singleton_pid(role) if role else None
        if pid and _pid_alive(pid):
            return pid
    return read_singleton_pid(role) if role else None


def ensure_supervisor(*, force: bool = False) -> dict:
    sw = switch_status()
    if sw.get("emergency_stop"):
        return {"started": False, "reason": "emergency_stop"}
    age = heartbeat_age_seconds()
    pid = read_singleton_pid("doofus_supervisor")
    alive = _pid_alive(pid) if pid else False
    stale = age is None or age > STALE_SECONDS
    if alive and not stale and not force:
        return {"started": False, "reason": "healthy", "pid": pid}
    if alive and stale:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        _append_log("supervisor_stale_kill", {"pid": pid, "age": age})
    from doofus.supervisor.process_singleton import cleanup_stale_lock
    cleanup_stale_lock("doofus_supervisor")
    new_pid = _spawn("doofus.supervisor.doofus_24_7_supervisor")
    _append_log("supervisor_start", {"pid": new_pid})
    return {"started": True, "pid": new_pid}


def _kill_port_listeners(port: int) -> list[int]:
    """Best-effort kill of processes bound to localhost:port (Windows)."""
    if sys.platform != "win32":
        return []
    killed: list[int] = []
    try:
        proc = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return killed
    needle = f"127.0.0.1:{port}"
    pids: set[int] = set()
    for line in (proc.stdout or "").splitlines():
        if "LISTENING" not in line or needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            pids.add(int(parts[-1]))
        except ValueError:
            continue
    for pid in sorted(pids):
        if pid <= 0:
            continue
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        killed.append(pid)
    return killed


def ensure_dashboard(*, force: bool = False) -> dict:
    if not _repair_lock():
        return {"started": False, "reason": "repair_in_progress"}
    try:
        return _ensure_dashboard_locked(force=force)
    finally:
        _release_repair_lock()


def _ensure_dashboard_locked(*, force: bool = False) -> dict:
    from doofus.dashboard.dashboard_health import dashboard_reachable

    if dashboard_reachable(timeout=1.0) and not force:
        return {"started": False, "reason": "port_open", "pid": read_singleton_pid("doofus_dashboard")}
    dash = dashboard_health()
    pid = read_singleton_pid("doofus_dashboard")
    alive = _pid_alive(pid) if pid else False
    if dash.get("reachable") and alive and not force:
        return {"started": False, "reason": "healthy", "pid": pid}
    if alive:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        _append_log("dashboard_restart_kill", {"pid": pid, "reachable": dash.get("reachable")})
    port_killed = _kill_port_listeners(8765)
    if port_killed:
        _append_log("dashboard_port_kill", {"pids": port_killed})
    from doofus.supervisor.process_singleton import cleanup_stale_lock

    cleanup_stale_lock("doofus_dashboard")
    import time

    time.sleep(1.5)
    new_pid = _spawn("doofus.dashboard.doofus_dashboard_app")
    for _ in range(45):
        if dashboard_reachable(timeout=2.0):
            live_pid = read_singleton_pid("doofus_dashboard")
            _append_log("dashboard_start", {"pid": live_pid or new_pid, "reachable": True})
            return {"started": True, "pid": live_pid or new_pid, "reachable": True}
        time.sleep(1)
    _append_log("dashboard_start", {"pid": new_pid, "reachable": False})
    return {"started": True, "pid": new_pid, "reachable": False}


def repair_all(*, allow_supervisor: bool = True) -> dict:
    from doofus.runtime.safe_cleanup import run_safe_cleanup

    cleanup = run_safe_cleanup()
    actions = {"cleanup": cleanup}
    # Skip auto-dashboard spawn if UI already serving (avoids empty duplicate races)
    port_file = STATE / "dashboard_port.json"
    port = 8765
    if port_file.exists():
        try:
            port = int(json.loads(port_file.read_text(encoding="utf-8")).get("port", 8765))
        except Exception:
            pass
    from doofus.dashboard.dashboard_health import dashboard_reachable
    if dashboard_reachable(port=port, timeout=1.0):
        actions["dashboard"] = {"started": False, "reason": "ui_already_serving", "port": port}
    else:
        actions["dashboard"] = ensure_dashboard()
    if allow_supervisor and switch_status().get("may_run"):
        actions["supervisor"] = ensure_supervisor()
    else:
        actions["supervisor"] = {"started": False, "reason": "may_run_false_or_disabled"}
    return actions
