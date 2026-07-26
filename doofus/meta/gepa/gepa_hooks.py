"""GEPA instrumentation hooks for loop runner."""
from __future__ import annotations

import sqlite3

from doofus.meta.gepa.trace_collector import record_trace
from doofus.meta.gepa.prompt_store import get_active_hash


def on_candidate_scored(
    *,
    generation: int,
    candidate: dict,
    scores: dict,
    baseline: float,
    rejection_reason: str = "",
    arena_results: list | None = None,
    traits_before: list | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    arena_str = ""
    if arena_results:
        arena_str = ",".join(r.get("result", "") for r in arena_results[:3])
    score_delta = float(scores.get("score_total") or 0) - float(baseline)
    record_trace(
        cycle_id=generation,
        candidate_id=candidate.get("candidate_id", ""),
        prompt_text=get_active_hash("mutation"),
        rejection_reason=rejection_reason,
        score_delta=score_delta,
        arena_result=arena_str,
        traits_before=traits_before or candidate.get("traits"),
        traits_after=candidate.get("traits"),
        conn=conn,
    )
