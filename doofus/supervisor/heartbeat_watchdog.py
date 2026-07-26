"""Heartbeat staleness detection."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

from doofus.core.doofus_paths import HEARTBEATS, METRICS_DB

STALE_WARN = int(os.environ.get("DOOFUS_HEARTBEAT_STALE_WARN_SECONDS", "300"))
STALE_RESTART = int(os.environ.get("DOOFUS_HEARTBEAT_STALE_RESTART_SECONDS", "900"))
_SUPERVISOR_HEARTBEAT_SQL = """
SELECT created_at
FROM heartbeats
WHERE status LIKE 'supervisor_%' OR status LIKE 'cycle_%'
ORDER BY id DESC LIMIT 1
"""


def _is_supervisor_status(status: str | None) -> bool:
    status = status or ""
    return status.startswith("supervisor_") or status.startswith("cycle_")


def _latest_heartbeat_file_age() -> float | None:
    path = HEARTBEATS / "latest.json"
    if not path.exists():
        return None
    try:
        import json

        doc = json.loads(path.read_text(encoding="utf-8"))
        if not _is_supervisor_status(doc.get("status")):
            return None
        ts = datetime.fromisoformat(str(doc["generated_at"]).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
    except Exception:
        return None


def heartbeat_age_seconds() -> float | None:
    file_age = _latest_heartbeat_file_age()
    if file_age is not None:
        return file_age
    try:
        conn = sqlite3.connect(METRICS_DB, timeout=5.0)
        row = conn.execute(_SUPERVISOR_HEARTBEAT_SQL).fetchone()
        conn.close()
        if not row:
            return None
        ts = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
    except Exception:
        return None


def heartbeat_status() -> dict:
    age = heartbeat_age_seconds()
    if age is None:
        return {"age_seconds": None, "status": "none", "stale_warn": False, "stale_restart": False}
    return {
        "age_seconds": round(age, 1),
        "status": "fresh" if age < STALE_WARN else "stale_warn" if age < STALE_RESTART else "stale_restart",
        "stale_warn": age >= STALE_WARN,
        "stale_restart": age >= STALE_RESTART,
        "stale_warn_threshold": STALE_WARN,
        "stale_restart_threshold": STALE_RESTART,
    }
