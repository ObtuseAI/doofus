"""Persist cycle metrics to SQLite."""
from __future__ import annotations

import sqlite3

from doofus.core.doofus_events import utc_now


def log_mutation(conn: sqlite3.Connection, candidate_id: str, mutation_type: str) -> None:
    conn.execute(
        "INSERT INTO mutations (candidate_id, mutation_type, created_at) VALUES (?,?,?)",
        (candidate_id, mutation_type, utc_now()),
    )


def log_arena_results(conn: sqlite3.Connection, results: list[dict]) -> None:
    rows = []
    now = utc_now()
    for r in results:
        cid = r.get("candidate_id")
        arena = r.get("arena")
        if not cid or not arena:
            continue
        rows.append((
            cid, arena, r.get("result", ""),
            r.get("score"), r.get("steps"), r.get("trace_ref"),
            r.get("created_at", now),
        ))
    if rows:
        conn.executemany(
            """INSERT INTO arena_results (candidate_id, arena, result, score, steps, trace_ref, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            rows,
        )


def log_safety_event(conn: sqlite3.Connection, event_type: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO safety_events (event_type, detail, created_at) VALUES (?,?,?)",
        (event_type, detail[:500], utc_now()),
    )


def upsert_candidate(conn: sqlite3.Connection, c: dict, scores: dict, promo: dict) -> None:
    traits = c.get("traits") or []
    conn.execute(
        """INSERT OR REPLACE INTO candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            c["candidate_id"], c.get("parent_id"), c.get("generation", 0),
            ",".join(traits) if isinstance(traits, list) else str(traits),
            c.get("mutation_type", "unknown"),
            ",".join(c.get("arena_targets") or []),
            c.get("status", "scored"),
            scores.get("score_total", 0), scores.get("score_safety", 0),
            scores.get("score_replay", 0), scores.get("score_generalization", 0),
            scores.get("score_compounding", 0), scores.get("score_recursive_learning", 0),
            c.get("rejection_reason"), promo.get("promotion_status", "rejected"), utc_now(),
        ),
    )


def log_score_components(conn: sqlite3.Connection, candidate_id: str, scores: dict) -> None:
    now = utc_now()
    rows = [
        (candidate_id, metric, float(value), now)
        for metric, value in scores.items()
        if metric.startswith("score_") or metric in ("proof_density_score", "bloat_penalty", "replay_stability_score")
    ]
    if rows:
        conn.executemany(
            "INSERT INTO scores (candidate_id, metric, value, created_at) VALUES (?,?,?,?)",
            rows,
        )
