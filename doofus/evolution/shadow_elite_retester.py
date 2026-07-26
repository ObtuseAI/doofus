"""Retest shadow elites via proof builder."""
from __future__ import annotations

from doofus.evolution.shadow_elite_archive import _load, retire_shadow_elite
from doofus.proof.proof_builder_queue import enqueue


def retest_shadow_elites(*, limit: int = 10) -> dict:
    entries = _load()[:limit]
    retested = 0
    for e in entries:
        if e.get("upgraded"):
            continue
        if enqueue(e["candidate_id"], score=float(e.get("score") or 0), reason="shadow_elite_retest"):
            retested += 1
    return {"retested": retested, "candidates": len(entries)}


def retire_failed_shadow(candidate_id: str) -> None:
    retire_shadow_elite(candidate_id, reason="proof_failed_repeatedly")
