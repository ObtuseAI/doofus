"""Safe SQLite queries for live dashboard."""
from __future__ import annotations
import sqlite3
from typing import Any
from doofus.core.doofus_paths import METRICS_DB

DEFAULT_LIMIT = 200

def _connect() -> sqlite3.Connection | None:
    try:
        from doofus.core.metrics_db import connect_metrics_db
        conn = connect_metrics_db(timeout=1.0)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None

def _rows(sql: str, params: tuple = (), limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    conn = _connect()
    if not conn:
        return []
    try:
        cur = conn.execute(sql, params)
        out = [dict(r) for r in cur.fetchmany(limit)]
        conn.close()
        return out
    except sqlite3.Error:
        try:
            conn.close()
        except Exception:
            pass
        return []

def _scalar(sql: str, params: tuple = (), default: Any = 0) -> Any:
    conn = _connect()
    if not conn:
        return default
    try:
        row = conn.execute(sql, params).fetchone()
        conn.close()
        return row[0] if row and row[0] is not None else default
    except sqlite3.Error:
        try:
            conn.close()
        except Exception:
            pass
        return default

def count_table(table: str) -> int:
    return int(_scalar(f"SELECT COUNT(*) FROM {table}", default=0))

def recent_cycles(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM cycles ORDER BY cycle_id DESC LIMIT ?", (limit,), limit)

def recent_candidates(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM candidates ORDER BY created_at DESC LIMIT ?", (limit,), limit)

def recent_promotions(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM promotions ORDER BY id DESC LIMIT ?", (limit,), limit)

def recent_rejections(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM rejections ORDER BY id DESC LIMIT ?", (limit,), limit)

def recent_model_calls(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM model_calls ORDER BY id DESC LIMIT ?", (limit,), limit)

def recent_safety_events(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM safety_events ORDER BY id DESC LIMIT ?", (limit,), limit)

def recent_heartbeats(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM heartbeats ORDER BY id DESC LIMIT ?", (limit,), limit)

def recent_dashboard_events(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM dashboard_events ORDER BY id DESC LIMIT ?", (limit,), limit)

def score_by_generation(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        """SELECT generation,
           COUNT(*) AS count,
           AVG(score_total) AS avg_total,
           MAX(score_total) AS best_total,
           AVG(score_compounding) AS avg_compounding,
           AVG(score_recursive_learning) AS avg_recursive,
           AVG(score_generalization) AS avg_generalization,
           AVG(score_replay) AS avg_replay,
           AVG(score_safety) AS avg_safety
           FROM candidates GROUP BY generation ORDER BY generation LIMIT ?""",
        (limit,),
        limit,
    )

def rejection_reason_counts(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        "SELECT reason, COUNT(*) AS count FROM rejections GROUP BY reason ORDER BY count DESC LIMIT ?",
        (limit,),
        limit,
    )

def mutation_type_counts(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        "SELECT mutation_type, COUNT(*) AS count FROM candidates GROUP BY mutation_type ORDER BY count DESC LIMIT ?",
        (limit,),
        limit,
    )

def candidate_status_counts() -> list[dict]:
    return _rows("SELECT status, COUNT(*) AS count FROM candidates GROUP BY status")

def model_calls_timeseries(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT id, model, provider, tokens_est, cost_est, created_at FROM model_calls ORDER BY id DESC LIMIT ?", (limit,), limit)

def promotions_over_time(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT created_at FROM promotions ORDER BY id DESC LIMIT ?", (limit,), limit)

def rejections_over_time(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT created_at, reason FROM rejections ORDER BY id DESC LIMIT ?", (limit,), limit)

def arena_results(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows("SELECT * FROM arena_results ORDER BY id DESC LIMIT ?", (limit,), limit)

def top_candidates(limit: int = 20) -> list[dict]:
    return _rows("SELECT * FROM candidates ORDER BY score_total DESC LIMIT ?", (limit,), limit)

def lineage_rows(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        "SELECT candidate_id, parent_id, generation, score_total, status FROM candidates WHERE parent_id IS NOT NULL ORDER BY generation DESC LIMIT ?",
        (limit,),
        limit,
    )

def candidate_score_timeseries(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        """SELECT rowid, candidate_id, generation, created_at, score_total, score_safety,
           score_replay, score_generalization, score_compounding, score_recursive_learning, status
           FROM candidates ORDER BY rowid ASC LIMIT ?""",
        (limit,),
        limit,
    )

def candidates_per_generation(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        "SELECT generation, COUNT(*) AS count FROM candidates GROUP BY generation ORDER BY generation ASC LIMIT ?",
        (limit,),
        limit,
    )

def cumulative_promotions(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        """SELECT id, created_at,
           (SELECT COUNT(*) FROM promotions p2 WHERE p2.id <= promotions.id) AS cumulative
           FROM promotions ORDER BY id ASC LIMIT ?""",
        (limit,),
        limit,
    )

def cumulative_rejections(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        """SELECT id, created_at, reason,
           (SELECT COUNT(*) FROM rejections r2 WHERE r2.id <= rejections.id) AS cumulative
           FROM rejections ORDER BY id ASC LIMIT ?""",
        (limit,),
        limit,
    )

def model_call_cost_series(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        """SELECT id, created_at, cost_est, tokens_est, provider,
           (SELECT SUM(cost_est) FROM model_calls m2 WHERE m2.id <= model_calls.id) AS cumulative_cost
           FROM model_calls ORDER BY id ASC LIMIT ?""",
        (limit,),
        limit,
    )


def metacognitive_predictions(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        """SELECT * FROM metacognitive_predictions
           ORDER BY created_at ASC LIMIT ?""",
        (limit,),
        limit,
    )


def metacognitive_events(limit: int = DEFAULT_LIMIT) -> list[dict]:
    return _rows(
        """SELECT * FROM metacognitive_events
           ORDER BY id DESC LIMIT ?""",
        (limit,),
        limit,
    )
