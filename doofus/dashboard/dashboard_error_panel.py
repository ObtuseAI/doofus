"""Last error from checkpoint/heartbeat."""
from __future__ import annotations
import json
from doofus.core.doofus_paths import HEARTBEATS, STATE

def error_panel() -> dict:
    err = ""
    cp = STATE / "cycle_checkpoint.json"
    if cp.exists():
        err = json.loads(cp.read_text(encoding="utf-8")).get("data", {}).get("last_error", "")
    return {"last_error": err[:500]}
