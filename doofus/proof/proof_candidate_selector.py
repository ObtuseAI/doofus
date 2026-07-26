"""Select candidates for proof-builder rescue."""
from __future__ import annotations

import time

from doofus.proof.high_score_rejection_miner import (
    MINER_DEADLINE_EXCEEDED,
    MINER_DEFERRED_DEADLINE,
    mine_high_score_rejections,
)
from doofus.proof.proof_builder_queue import enqueue, top_n


def select_and_enqueue(*, limit: int | None = None, deadline_monotonic: float | None = None, generation: int | None = None) -> dict:
    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
        return {
            "enqueued": 0,
            "skipped": 0,
            "mined_count": 0,
            "timed_out": True,
            "classification": MINER_DEFERRED_DEADLINE,
            "timed_out_stage": "before_mine",
        }
    row_limit = limit or top_n()
    mined = mine_high_score_rejections(
        limit=max(row_limit, 20),
        deadline_monotonic=deadline_monotonic,
        enrich=False,
        generation=generation,
        include_best_ever=False,
    )
    classification = mined.get("classification", "HIGH_SCORE_MINER_OK")
    if mined.get("timed_out") or classification in {MINER_DEFERRED_DEADLINE, MINER_DEADLINE_EXCEEDED}:
        return {
            "enqueued": 0,
            "skipped": 0,
            "mined_count": mined.get("count_score_gte_threshold", 0),
            "timed_out": True,
            "classification": classification,
            "timed_out_stage": mined.get("timed_out_stage", "mine_high_score_rejections"),
            "decision": mined.get("decision", classification),
        }
    enqueued = 0
    skipped = 0
    for row in mined.get("top_100", [])[:row_limit]:
        cid = row["candidate_id"]
        if enqueue(cid, score=float(row.get("score_total") or 0), reason=row.get("rejection_reason") or "high_score"):
            enqueued += 1
        else:
            skipped += 1
    return {
        "enqueued": enqueued,
        "skipped": skipped,
        "mined_count": mined.get("count_score_gte_threshold", 0),
        "classification": classification,
    }
