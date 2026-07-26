"""Record live proof outcomes in metrics DB — no secrets."""
from __future__ import annotations

import json
import sqlite3
from doofus.core import doofus_paths
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_state import init_db


def record_live_proof(result: dict) -> None:
    init_db()
    safe = {k: v for k, v in result.items() if "key" not in k.lower() and "secret" not in k.lower()}
    detail = json.dumps(safe)[:1000]
    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=5.0)
    conn.execute(
        "INSERT INTO dashboard_events (event_type, detail, created_at) VALUES (?,?,?)",
        ("live_model_proof", detail, utc_now()),
    )
    conn.commit()
    conn.close()
