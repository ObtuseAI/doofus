"""GEP EvolutionEvent emitter."""
from __future__ import annotations

import json
import sqlite3

from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import STATE
from doofus.core.metrics_db import metrics_conn
from doofus.meta.gep.gep_schema import EvolutionEvent

EVENTS_FILE = STATE / "gep" / "events.jsonl"


def emit(
    event_type: str,
    payload: dict | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> EvolutionEvent:
    evt = EvolutionEvent(event_type=event_type, payload=payload or {}, created_at=utc_now())
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(evt.model_dump_json() + "\n")
    try:
        if conn is not None:
            conn.execute(
                "INSERT INTO gep_events (event_type, payload, created_at) VALUES (?,?,?)",
                (event_type, json.dumps(payload or {}, default=str)[:2000], evt.created_at),
            )
        else:
            with metrics_conn() as owned_conn:
                owned_conn.execute(
                    "INSERT INTO gep_events (event_type, payload, created_at) VALUES (?,?,?)",
                    (event_type, json.dumps(payload or {}, default=str)[:2000], evt.created_at),
                )
    except Exception as exc:
        from doofus.core.pipeline_log import pipeline_warn
        pipeline_warn("gep_event_db", f"insert failed type={event_type}", exc=exc)
    return evt


def recent_events(limit: int = 20) -> list[dict]:
    if not EVENTS_FILE.exists():
        return []
    lines = EVENTS_FILE.read_text(encoding="utf-8").strip().splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
