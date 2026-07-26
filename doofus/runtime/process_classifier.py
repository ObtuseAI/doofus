"""Classify Doofus Python processes for safe cleanup."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class ProcessInfo:
    pid: int
    commandline: str
    role: str


def classify_commandline(cmd: str) -> str:
    c = cmd.lower()
    if "windows_runtime_manager" in c:
        return "runtime_manager"
    if "doofus_24_7_supervisor" in c:
        return "supervisor"
    if "doofus_dashboard_app" in c:
        return "dashboard"
    if "runtime_closure_orchestrator" in c:
        return "validation_runner"
    if "doofus_hourly_autopilot" in c or "doofus_session_cleanup" in c:
        return "autopilot_session"
    if "supervisor_watchdog" in c or "dashboard_watchdog" in c:
        return "watchdog"
    if "-c" in c and "doofus" in c:
        return "tool"
    if "doofus" in c:
        return "orphan"
    return "unknown"


def _fetch_processes() -> list[ProcessInfo]:
    try:
        ps_script = (
            "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" -ErrorAction SilentlyContinue | "
            "Where-Object { $_.CommandLine -match 'doofus' } | "
            "ForEach-Object { [PSCustomObject]@{ ProcessId = $_.ProcessId; CommandLine = $_.CommandLine } } | "
            "ConvertTo-Json -Compress"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=3,
        )
        out = (proc.stdout or "").strip()
        if not out or proc.returncode != 0:
            return []
        import json
        raw = json.loads(out)
        if isinstance(raw, dict):
            raw = [raw]
        result: list[ProcessInfo] = []
        for item in raw:
            cmd = str(item.get("CommandLine") or "")
            pid = int(item["ProcessId"])
            result.append(ProcessInfo(pid=pid, commandline=cmd, role=classify_commandline(cmd)))
        return result
    except Exception:
        return []


def list_doofus_processes() -> list[dict]:
    """Enumerate live Doofus python processes plus singleton lock holders."""
    from doofus.runtime.process_registry import PROTECTED_ROLES
    from doofus.supervisor.process_singleton import read_singleton_pid, _pid_alive

    rows: list[dict] = []
    seen: set[int] = set()
    for info in _fetch_processes():
        rows.append({
            "pid": info.pid,
            "role": info.role,
            "commandline": info.commandline,
            "alive": True,
        })
        seen.add(info.pid)
    for role in PROTECTED_ROLES:
        pid = read_singleton_pid(role)
        if pid and pid not in seen:
            rows.append({
                "pid": pid,
                "role": role,
                "commandline": f"singleton:{role}",
                "alive": _pid_alive(pid),
            })
    return rows
