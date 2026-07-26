"""Kill zombie dashboard and start exactly one fresh instance."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv_doofus" / "Scripts" / "python.exe"
PORT_FILE = ROOT / "runtime" / "state" / "dashboard_port.json"
LOCK = ROOT / "runtime" / "state" / "doofus_dashboard.pid"
REPAIR_LOCK = ROOT / "runtime" / "state" / "runtime_repair.lock"
LOG = ROOT / "runtime" / "state" / "dashboard_start.log"
FALLBACK_PORTS = (8765, 8766, 8767, 8768)


def _pids_on_port(port: int) -> set[int]:
    pids: set[int] = set()
    if sys.platform != "win32":
        return pids
    try:
        proc = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=5)
        needle = f"127.0.0.1:{port}"
        for line in (proc.stdout or "").splitlines():
            if needle not in line:
                continue
            parts = line.split()
            if parts:
                try:
                    pids.add(int(parts[-1]))
                except ValueError:
                    pass
    except Exception:
        pass
    return pids


def _kill_pid(pid: int) -> bool:
    proc = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    return proc.returncode == 0


def _dashboard_pids(port: int) -> set[int]:
    pids = _pids_on_port(port)
    if LOCK.exists():
        try:
            pids.add(int(LOCK.read_text(encoding="utf-8").strip()))
        except ValueError:
            pass
    return {p for p in pids if p > 0}


def _port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except Exception:
        return False


def _pick_port() -> int:
    """Use 8765 unless blocked by an unkillable zombie — then try fallbacks."""
    for port in FALLBACK_PORTS:
        if not _port_open(port):
            return port
        pids = _pids_on_port(port)
        killed_any = any(_kill_pid(pid) for pid in pids)
        if killed_any:
            time.sleep(1.5)
            if not _port_open(port):
                return port
    # All candidate ports busy — use first fallback not listening
    for port in FALLBACK_PORTS[1:]:
        if not _port_open(port):
            return port
    return FALLBACK_PORTS[0]


def _http_ok(port: int, timeout: float = 4.0) -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=timeout) as resp:
            body = resp.read(8000).decode("utf-8", errors="replace")
            return resp.status == 200 and len(body) > 300 and "nicegui" in body.lower()
    except Exception:
        return False


def _ready(port: int) -> bool:
    if _http_ok(port, timeout=3.0):
        return True
    if not _port_open(port, timeout=1.0):
        return False
    if not LOG.exists():
        return False
    text = LOG.read_text(encoding="utf-8", errors="replace")
    return "NiceGUI ready" in text and "duplicate instance" not in text


def main() -> int:
    os.chdir(ROOT)
    # Stop auto-spawners that race and create empty duplicate instances
    if sys.platform == "win32":
        try:
            subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                    "Where-Object { $_.CommandLine -match 'windows_runtime_manager|doofus_dashboard_app' } | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
                ],
                capture_output=True,
                timeout=12,
            )
        except Exception:
            pass
    port = _pick_port()
    PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    PORT_FILE.write_text(json.dumps({"port": port}), encoding="utf-8")

    if _ready(port):
        print(f"OK dashboard already on http://127.0.0.1:{port}")
        return 0

    _kill_pids = _dashboard_pids(port)
    for pid in sorted(_kill_pids):
        _kill_pid(pid)
    LOCK.unlink(missing_ok=True)
    REPAIR_LOCK.unlink(missing_ok=True)
    from doofus.supervisor.process_singleton import clear_lock_unless_pid_listening
    clear_lock_unless_pid_listening("doofus_dashboard", port)
    time.sleep(1.5)

    env = os.environ.copy()
    env["DOOFUS_DASHBOARD_PORT"] = str(port)

    LOG.parent.mkdir(parents=True, exist_ok=True)
    logf = open(LOG, "w", encoding="utf-8")
    subprocess.Popen(
        ["cmd", "/c", "start", "", "/B", str(PY), "-u", "-m", "doofus.dashboard.doofus_dashboard_app"],
        cwd=str(ROOT),
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
    )
    logf.close()

    for i in range(45):
        if _ready(port):
            print(f"OK dashboard UI on http://127.0.0.1:{port} after {i + 1}s")
            return 0
        time.sleep(1)

    tail = LOG.read_text(encoding="utf-8", errors="replace")[-3000:] if LOG.exists() else ""
    print(f"FAIL dashboard not serving on port {port}\n{tail}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
