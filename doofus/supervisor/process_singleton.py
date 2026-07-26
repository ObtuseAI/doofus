"""Single-instance guard for supervisor and dashboard."""
from __future__ import annotations
import os
import sys
from pathlib import Path
from doofus.core.doofus_paths import STATE

def _lock_path(name: str) -> Path:
    return STATE / f"{name}.pid"

def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, PermissionError):
        return False

def acquire_singleton(name: str) -> bool:
    """Return True if this process acquired the lock."""
    STATE.mkdir(parents=True, exist_ok=True)
    path = _lock_path(name)
    pid = os.getpid()
    if path.exists():
        try:
            old = int(path.read_text(encoding="utf-8").strip())
        except ValueError:
            old = -1
        if _pid_alive(old) and old != pid:
            return False
    path.write_text(str(pid), encoding="utf-8")
    return True

def release_singleton(name: str) -> None:
    path = _lock_path(name)
    if path.exists():
        try:
            if int(path.read_text(encoding="utf-8").strip()) == os.getpid():
                path.unlink(missing_ok=True)
        except ValueError:
            path.unlink(missing_ok=True)

def cleanup_stale_lock(name: str) -> bool:
    """Remove lock if PID is dead. Return True if lock cleared or valid."""
    path = _lock_path(name)
    if not path.exists():
        return True
    try:
        old = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        path.unlink(missing_ok=True)
        return True
    if not _pid_alive(old):
        path.unlink(missing_ok=True)
        return True
    return False


def read_singleton_pid(name: str) -> int | None:
    path = _lock_path(name)
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def clear_lock_unless_pid_listening(name: str, port: int, *, host: str = "127.0.0.1") -> bool:
    """Remove lock if holder is alive but not listening on host:port (cross-port zombie)."""
    path = _lock_path(name)
    if not path.exists():
        return True
    try:
        old = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        path.unlink(missing_ok=True)
        return True
    if not _pid_alive(old):
        path.unlink(missing_ok=True)
        return True
    if _pid_listening_on(old, host, port):
        return False
    path.unlink(missing_ok=True)
    return True


def _pid_listening_on(pid: int, host: str, port: int) -> bool:
    if sys.platform != "win32":
        return False
    import subprocess
    try:
        proc = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        needle = f"{host}:{port}"
        for line in (proc.stdout or "").splitlines():
            if "LISTENING" not in line or needle not in line:
                continue
            parts = line.split()
            if parts and int(parts[-1]) == pid:
                return True
    except Exception:
        pass
    return False
