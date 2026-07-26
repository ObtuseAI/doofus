"""GEPA trace collection for reflective prompt evolution."""
from __future__ import annotations

import hashlib
import json
import sqlite3

from doofus.config.meta_evolution_config import gepa_enabled
from doofus.core.atomic_json import append_jsonl, load_json
from doofus.core.doofus_events import utc_now
from doofus.core.doofus_paths import STATE
from doofus.core.metrics_db import metrics_conn
from doofus.core.pipeline_log import pipeline_warn

TRACE_DIR = STATE / "gepa"
TRACE_JSONL = TRACE_DIR / "traces.jsonl"


def _prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def record_trace(
    *,
    cycle_id: int,
    candidate_id: str,
    prompt_text: str = "",
    rejection_reason: str = "",
    score_delta: float = 0.0,
    arena_result: str = "",
    traits_before: list | None = None,
    traits_after: list | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict:
    if not gepa_enabled():
        return {"skipped": True}
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    ph = _prompt_hash(prompt_text) if prompt_text else ""
    row = {
        "cycle_id": cycle_id,
        "candidate_id": candidate_id,
        "prompt_hash": ph,
        "rejection_reason": rejection_reason[:200],
        "score_delta": round(float(score_delta), 4),
        "arena_result": arena_result[:200],
        "traits_before": traits_before or [],
        "traits_after": traits_after or [],
        "created_at": utc_now(),
    }
    append_jsonl(TRACE_JSONL, row)
    try:
        if conn is not None:
            conn.execute(
                """INSERT INTO gepa_traces (cycle_id, candidate_id, prompt_hash, rejection_reason,
                   score_delta, arena_result, traits_before, traits_after, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    cycle_id, candidate_id, ph, row["rejection_reason"], row["score_delta"],
                    row["arena_result"], json.dumps(traits_before or []), json.dumps(traits_after or []),
                    row["created_at"],
                ),
            )
        else:
            with metrics_conn() as live_conn:
                live_conn.execute(
                    """INSERT INTO gepa_traces (cycle_id, candidate_id, prompt_hash, rejection_reason,
                       score_delta, arena_result, traits_before, traits_after, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        cycle_id, candidate_id, ph, row["rejection_reason"], row["score_delta"],
                        row["arena_result"], json.dumps(traits_before or []), json.dumps(traits_after or []),
                        row["created_at"],
                    ),
                )
    except Exception as exc:
        pipeline_warn("gepa_trace_db", f"insert failed cid={candidate_id}", exc=exc)
    return row


def count_traces_since(last_id: int = 0) -> int:
    try:
        with metrics_conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM gepa_traces WHERE id > ?", (last_id,)).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        if not TRACE_JSONL.exists():
            return 0
        return sum(1 for _ in TRACE_JSONL.open(encoding="utf-8"))


def sample_traces(limit: int = 20) -> list[dict]:
    traces: list[dict] = []
    if TRACE_JSONL.exists():
        lines = TRACE_JSONL.read_text(encoding="utf-8").strip().splitlines()
        for line in lines[-limit:]:
            try:
                traces.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return traces
