"""Proof-builder queue for high-scoring under-proven candidates."""
from __future__ import annotations

import json
import os
import time

from doofus.core.doofus_paths import STATE
from doofus.core.doofus_events import utc_now
from doofus.core.atomic_json import append_jsonl

QUEUE_FILE = STATE / "proof_builder_queue.json"
STATS_FILE = STATE / "proof_builder_stats.json"
EVENTS_FILE = STATE / "proof_builder_queue_events.jsonl"


def proof_builder_enabled() -> bool:
    return os.environ.get("DOOFUS_PROOF_BUILDER_MODE", "1") == "1"


def max_retries() -> int:
    return int(os.environ.get("DOOFUS_PROOF_BUILDER_MAX_RETRIES", "3"))


def top_n() -> int:
    return int(os.environ.get("DOOFUS_PROOF_BUILDER_TOP_N", "100"))


def _load_queue() -> list:
    if not QUEUE_FILE.exists():
        return []
    return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))


def _save_queue(entries: list) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _load_stats() -> dict:
    if not STATS_FILE.exists():
        return {"successes": 0, "failures": 0, "entries_total": 0}
    return json.loads(STATS_FILE.read_text(encoding="utf-8"))


def _save_stats(stats: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(stats, indent=2), encoding="utf-8")


def _record_queue_event(
    *,
    event_type: str,
    candidate_id: str,
    score: float,
    reason: str,
    generation: int | None,
    enqueued: bool,
    queue_size: int,
    write_duration_ms: float,
) -> None:
    append_jsonl(
        EVENTS_FILE,
        {
            "timestamp_utc": utc_now(),
            "event_type": event_type,
            "candidate_id": candidate_id,
            "score": float(score),
            "reason": reason,
            "generation": generation,
            "enqueued": bool(enqueued),
            "queue_size": int(queue_size),
            "queue_path": str(QUEUE_FILE),
            "write_duration_ms": round(write_duration_ms, 2),
        },
    )


def enqueue(
    candidate_id: str,
    *,
    score: float,
    reason: str = "proof_density_weak",
    generation: int | None = None,
    return_details: bool = False,
) -> bool | dict:
    started = time.perf_counter()
    entries = _load_queue()
    if any(e.get("candidate_id") == candidate_id for e in entries):
        details = {
            "candidate_id": candidate_id,
            "generation": generation,
            "enqueued": False,
            "reason": "already_present",
            "queue_path": str(QUEUE_FILE),
            "queue_size": len(entries),
            "write_duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
        }
        _record_queue_event(
            event_type="enqueue_skipped",
            candidate_id=candidate_id,
            score=score,
            reason=reason,
            generation=generation,
            enqueued=False,
            queue_size=len(entries),
            write_duration_ms=details["write_duration_ms"],
        )
        return details if return_details else False
    if len(entries) >= top_n():
        details = {
            "candidate_id": candidate_id,
            "generation": generation,
            "enqueued": False,
            "reason": "queue_full",
            "queue_path": str(QUEUE_FILE),
            "queue_size": len(entries),
            "write_duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
        }
        _record_queue_event(
            event_type="enqueue_skipped",
            candidate_id=candidate_id,
            score=score,
            reason=reason,
            generation=generation,
            enqueued=False,
            queue_size=len(entries),
            write_duration_ms=details["write_duration_ms"],
        )
        return details if return_details else False
    entries.append({
        "candidate_id": candidate_id,
        "score": score,
        "reason": reason,
        "generation": generation,
        "retries": 0,
        "outcome": "pending",
        "enqueued_at": utc_now(),
    })
    _save_queue(entries)
    stats = _load_stats()
    stats["entries_total"] = stats.get("entries_total", 0) + 1
    _save_stats(stats)
    details = {
        "candidate_id": candidate_id,
        "generation": generation,
        "enqueued": True,
        "reason": reason,
        "queue_path": str(QUEUE_FILE),
        "queue_size": len(entries),
        "write_duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
    }
    _record_queue_event(
        event_type="enqueue",
        candidate_id=candidate_id,
        score=score,
        reason=reason,
        generation=generation,
        enqueued=True,
        queue_size=len(entries),
        write_duration_ms=details["write_duration_ms"],
    )
    return details if return_details else True


def dequeue(candidate_id: str) -> None:
    entries = [e for e in _load_queue() if e.get("candidate_id") != candidate_id]
    _save_queue(entries)


def update_entry(candidate_id: str, **fields) -> None:
    entries = _load_queue()
    for e in entries:
        if e.get("candidate_id") == candidate_id:
            e.update(fields)
    _save_queue(entries)


def pending_entries(limit: int = 20) -> list:
    entries = [e for e in _load_queue() if e.get("outcome") in ("pending", "proof_partial")]
    return entries[:limit]


def queue_summary() -> dict:
    entries = _load_queue()
    stats = _load_stats()
    outcomes: dict[str, int] = {}
    by_generation: dict[str, int] = {}
    for e in entries:
        o = e.get("outcome", "pending")
        outcomes[o] = outcomes.get(o, 0) + 1
        generation = str(e.get("generation")) if e.get("generation") is not None else "unknown"
        by_generation[generation] = by_generation.get(generation, 0) + 1
    return {
        "enabled": proof_builder_enabled(),
        "queue_path": str(QUEUE_FILE),
        "queue_size": len(entries),
        "pending": sum(1 for e in entries if e.get("outcome") in ("pending", "proof_partial")),
        "outcomes": outcomes,
        "by_generation": by_generation,
        "successes": stats.get("successes", 0),
        "failures": stats.get("failures", 0),
        "entries_total": stats.get("entries_total", 0),
    }


def record_success() -> None:
    stats = _load_stats()
    stats["successes"] = stats.get("successes", 0) + 1
    _save_stats(stats)


def record_failure() -> None:
    stats = _load_stats()
    stats["failures"] = stats.get("failures", 0) + 1
    _save_stats(stats)
