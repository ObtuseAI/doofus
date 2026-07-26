"""Single Doofus desktop launcher — runtime, supervisor, dashboard, browser."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv_doofus" / "Scripts" / "python.exe"
ZOMBIE_PID = 9572
PORT_FILE = ROOT / "runtime" / "state" / "dashboard_port.json"
LOG = ROOT / "runtime" / "state" / "dashboard_start.log"


def _pid_alive(pid: int) -> bool:
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return f" {pid} " in (proc.stdout or "")
    except Exception:
        return False


def _kill_pid(pid: int) -> bool:
    if pid == ZOMBIE_PID:
        return False
    try:
        proc = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            timeout=3,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _read_port() -> int:
    if PORT_FILE.exists():
        try:
            return int(json.loads(PORT_FILE.read_text(encoding="utf-8")).get("port", 8766))
        except Exception:
            pass
    return 8766 if _pid_alive(ZOMBIE_PID) else 8765


def _validate_ui(port: int) -> bool:
    try:
        import socket
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
    except Exception:
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=8) as resp:
            body = resp.read(12000).decode("utf-8", errors="replace")
            return resp.status == 200 and "nicegui" in body.lower()
    except Exception:
        return LOG.exists() and "NiceGUI ready" in LOG.read_text(encoding="utf-8", errors="replace")


def _open_browser(url: str) -> None:
    print(f"Opening {url}")
    if not webbrowser.open(url):
        os.startfile(url)  # type: ignore[attr-defined]


def _start_runtime_stack() -> None:
    from doofus.runtime.runtime_health import runtime_manager_health
    from doofus.runtime.runtime_repair import ensure_supervisor

    if not runtime_manager_health().get("active"):
        subprocess.Popen(
            ["cmd", "/c", "start", "", "/B", str(PY), "-u", "-m", "doofus.runtime.windows_runtime_manager", "--serve"],
            cwd=str(ROOT),
            env=os.environ.copy(),
        )
        print("Runtime manager started.")
        time.sleep(1)
    sup = ensure_supervisor()
    print(f"Supervisor: {sup}")


def main() -> int:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))

    port = _read_port()
    dashboard_up = _validate_ui(port)

    if _pid_alive(ZOMBIE_PID):
        print(f"Stopping zombie dashboard PID {ZOMBIE_PID}...")
        if _kill_pid(ZOMBIE_PID):
            print(f"Zombie PID {ZOMBIE_PID} stopped.")
            time.sleep(1)
            port = 8765
        else:
            print(f"WARN: could not kill PID {ZOMBIE_PID} — using port 8766.")
            port = 8766

    from doofus.safety.on_off_switch import clear_emergency, start
    from doofus.supervisor.process_singleton import clear_lock_unless_pid_listening

    clear_emergency()
    start()
    print("Doofus run switch enabled.")

    from doofus.config.meta_evolution_config import apply_defaults as apply_meta
    from doofus.config.proof_builder_runtime_config import bootstrap_autonomous_runtime
    apply_meta(force=True)
    bootstrap_autonomous_runtime(force=True)
    print("SOTA meta-evolution enabled (live arena, GEPA, MAP-Elites, CodeEvolve auto-apply).")

    _start_runtime_stack()
    clear_lock_unless_pid_listening("doofus_dashboard", port)

    if not dashboard_up:
        proc = subprocess.run([str(PY), str(ROOT / "scripts" / "doofus_kill_start_dashboard.py")])
        port = _read_port()
        if proc.returncode != 0 and not _validate_ui(port):
            print(f"ERROR: Dashboard failed on port {port}", file=sys.stderr)
            if LOG.exists():
                print(LOG.read_text(encoding="utf-8", errors="replace")[-2000:], file=sys.stderr)
            return 1

    url = f"http://127.0.0.1:{port}"
    if not _validate_ui(port):
        print(f"ERROR: Dashboard not responding at {url}", file=sys.stderr)
        return 1

    print(f"Doofus ready — dashboard at {url}")
    _open_browser(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
