"""Control panel metadata."""
from __future__ import annotations
from doofus.safety.on_off_switch import status

def control_panel() -> dict:
    return {"switch": status(), "writes_files_only": True}
