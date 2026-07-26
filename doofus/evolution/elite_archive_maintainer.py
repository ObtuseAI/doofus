"""Backfill and maintain elite archive from proof-backed promotions."""
from __future__ import annotations

import sqlite3
import time

from doofus.core.doofus_paths import METRICS_DB
from doofus.evolution.elite_archive import add_elite, get_elite_archive, pin_best_ever
from doofus.evolution.evolution_policy import elite_archive_size


def _past_deadline(deadline_monotonic: float | None) -> bool:
    return deadline_monotonic is not None and time.monotonic() >= deadline_monotonic


def backfill_from_promotions(*, limit: int | None = None, deadline_monotonic: float | None = None) -> dict:
    """Insert top proof-backed promotions into elite archive (no mass blind promote)."""
    if _past_deadline(deadline_monotonic):
        return {"added": 0, "skipped": 0, "timed_out": True, "timed_out_stage": "before_connect"}
    cap = limit or elite_archive_size()
    conn = sqlite3.connect(METRICS_DB, timeout=5.0)
    rows = conn.execute(
        """
        SELECT c.candidate_id, c.parent_id, c.generation, c.traits, c.mutation_type,
               COALESCE(c.score_total, s.value, 0) AS score_total
        FROM promotions p
        JOIN candidates c ON c.candidate_id = p.candidate_id
        LEFT JOIN scores s ON s.candidate_id = c.candidate_id AND s.metric = 'score_total'
        WHERE c.promotion_status = 'promoted' OR c.status = 'promoted'
        ORDER BY score_total DESC
        LIMIT ?
        """,
        (cap * 3,),
    ).fetchall()
    conn.close()
    added = 0
    skipped = 0
    for row in rows:
        if _past_deadline(deadline_monotonic):
            conn.close()
            return {"added": added, "skipped": skipped, "timed_out": True, "timed_out_stage": "backfill_loop"}
        candidate = {
            "candidate_id": row[0],
            "parent_id": row[1],
            "generation": row[2],
            "traits": row[3].split(",") if row[3] else [],
            "mutation_type": row[4],
            "source": "backfill",
        }
        score = float(row[5] or 0)
        if score < 0.72:
            skipped += 1
            continue
        result = add_elite(candidate, score)
        if result.get("skipped"):
            skipped += 1
        else:
            added += 1
    pin_best_ever()
    archive = get_elite_archive()
    return {"added": added, "skipped": skipped, **archive}


def maintain_elite_archive(*, deadline_monotonic: float | None = None) -> dict:
    """Run each supervisor cycle — backfill if archive under cap."""
    if _past_deadline(deadline_monotonic):
        return {"timed_out": True, "timed_out_stage": "maintain_elite_archive"}
    archive = get_elite_archive()
    count = int(archive.get("elite_archive_count") or 0)
    cap = int(archive.get("size_cap") or elite_archive_size())
    if count < min(5, cap):
        return backfill_from_promotions(limit=cap, deadline_monotonic=deadline_monotonic)
    pin_best_ever()
    return archive
