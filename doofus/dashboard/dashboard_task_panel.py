"""Task panel — query scheduled task status."""
from __future__ import annotations
import subprocess

def task_panel() -> dict:
    out = {}
    for name in ("Doofus-24-7-Supervisor", "Doofus-Local-Dashboard"):
        r = subprocess.run(["schtasks", "/Query", "/TN", name, "/FO", "LIST"], capture_output=True, text=True)
        out[name] = {"registered": r.returncode == 0, "summary": (r.stdout or r.stderr)[-300:]}
    return out
