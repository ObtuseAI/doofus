"""Write heartbeat files and DB."""
from __future__ import annotations
import json
from doofus.core import doofus_paths
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_state import write_heartbeat
from doofus.core.pipeline_log import pipeline_warn

def emit_heartbeat(status: str, detail: dict | None = None) -> dict:
    doofus_paths.HEARTBEATS.mkdir(parents=True, exist_ok=True)
    doc = {"status": status, "detail": detail or {}, "generated_at": utc_now()}
    path = doofus_paths.HEARTBEATS / "latest.json"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    try:
        write_heartbeat(status, json.dumps(detail or {}, default=str)[:500])
    except Exception as exc:
        pipeline_warn("heartbeat_db", f"{status} write failed", exc=exc)
    return doc
