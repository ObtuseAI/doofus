"""Load promoted parents for recursive candidate generation."""
from __future__ import annotations
import sqlite3
from doofus.core import doofus_paths
from doofus.core.doofus_state import init_db

def load_promoted_parents(limit: int = 3) -> list[dict]:
    init_db()
    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=2.0)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT c.candidate_id, c.parent_id, c.generation, c.traits, c.mutation_type,
                  c.arena_targets, c.score_total
           FROM candidates c
           INNER JOIN promotions p ON p.candidate_id = c.candidate_id
           ORDER BY p.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "candidate_id": r["candidate_id"],
            "parent_id": r["parent_id"],
            "generation": r["generation"],
            "traits": [t for t in (r["traits"] or "").split(",") if t],
            "mutation_type": r["mutation_type"],
            "arena_targets": [a for a in (r["arena_targets"] or "").split(",") if a],
            "score_total": r["score_total"],
        })
    return out

def load_top_scoring_parents(limit: int = 2) -> list[dict]:
    init_db()
    conn = sqlite3.connect(doofus_paths.METRICS_DB, timeout=2.0)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT candidate_id, parent_id, generation, traits, mutation_type, arena_targets, score_total
           FROM candidates ORDER BY score_total DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {
            "candidate_id": r["candidate_id"],
            "parent_id": r["parent_id"],
            "generation": r["generation"],
            "traits": [t for t in (r["traits"] or "").split(",") if t],
            "mutation_type": r["mutation_type"],
            "arena_targets": [a for a in (r["arena_targets"] or "").split(",") if a],
            "score_total": r["score_total"],
        }
        for r in rows
    ]
