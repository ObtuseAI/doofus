"""Windows scheduled task manifest."""
from __future__ import annotations

SUPERVISOR_TASK = "Doofus-24-7-Supervisor"
DASHBOARD_TASK = "Doofus-Local-Dashboard"
PYTHON = r"C:\sai-auth-doofus\.venv_doofus\Scripts\python.exe"
WORKDIR = r"C:\sai-auth-doofus"
SUPERVISOR_ACTION = f'"{PYTHON}" -m doofus.supervisor.doofus_24_7_supervisor'
DASHBOARD_ACTION = f'"{PYTHON}" -m doofus.dashboard.doofus_dashboard_app'

def task_manifest() -> dict:
    return {
        "classification": "DOOFUS_WINDOWS_TASK_MANIFEST_READY",
        "supervisor": {"name": SUPERVISOR_TASK, "action": SUPERVISOR_ACTION, "workdir": WORKDIR},
        "dashboard": {"name": DASHBOARD_TASK, "action": DASHBOARD_ACTION, "workdir": WORKDIR, "bind": "127.0.0.1:8765"},
    }
